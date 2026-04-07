import scrapy
import pymongo
from datetime import datetime,timedelta
import html2text
import re
from pymongo import MongoClient, errors
import time
from textblob import TextBlob
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from github import Github
import urllib.parse
import logging
import os
from urllib.parse import unquote
import logging
logging.getLogger("pymongo").setLevel(logging.ERROR)

# ---------------------- Logging Setup ----------------------
logging.basicConfig(
    filename="automation_run.log",
    level=logging.ERROR,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


class PgsqlBugSpider(scrapy.Spider):
    name = 'Automation'
    start_urls = ['https://www.postgresql.org/list/pgsql-bugs/']
    start_date = datetime(2025, 10, 28)

    new_issues_count = 0
    new_comments_count = 0
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = self.get_mongo_client()
        
        self.db = self.client["Automation_Bugs"]
        self.collection = self.db["threads_data"]

        # Load previously fetched Message_IDs
        self.existing_message_ids = set(
            message['Message_ID'] for message in self.collection.aggregate([
                {"$unwind": "$Messages"},
                {"$project": {"Message_ID": "$Messages.Message_ID"}}
            ])
        )
        self.comments_collection = self.db["comments"]

        #self.last_run_date = self.get_last_run_date()

        # Initialize sentiment analysis tools
        self.analyzer = SentimentIntensityAnalyzer()
        # GitHub API setup
        self.github_token = os.getenv("GITHUB_TOKEN")
        if not self.github_token:
            self.logger.error("❌ GitHub token missing. Set GITHUB_TOKEN env variable.")
            raise ValueError("GitHub token missing! Set GITHUB_TOKEN before running.")
        self.github_repo_name = "BharatDBPG/BharatDBMS-PG"
        self.github = Github(self.github_token)
        self.repo = self.github.get_repo(self.github_repo_name)
   

    def get_mongo_client(self):
        try:
            client = MongoClient("mongodb://localhost:27017/", serverSelectionTimeoutMS=5000)
            client.admin.command('ping')
            print("✅ Connected to MongoDB")
            return client
        except Exception as e:
            raise Exception("❌ MongoDB connection failed:", e)

    def normalize_subject(self, subject):
        """
        Normalize the thread subject by removing all prefixes (like Re:, Fwd:, Bug Reappear:)
        while preserving 't:' if it exists in between.
        """
        # Define the reply prefixes pattern, allowing for variations and spaces
        reply_prefixes = (
            r'^(?:'
            r'(Re|Fwd|FW|Antwort|Antw|AW|Ynt|回复|答复|回复：|Re\[\d+\]|[EXT]|Bug\s*Reappear)'
            r'[\s]*[:：]'      # Match ":" or "：" (Chinese colon)
            r')+'
        )

        # Iteratively remove prefixes until none remain
        while re.match(reply_prefixes, subject, flags=re.IGNORECASE):
            subject = re.sub(reply_prefixes, '', subject, flags=re.IGNORECASE).strip()

        # Ensure 't:' in between words is preserved
        words = subject.split()
        cleaned_words = []
        for word in words:
            if word.lower() == "t:":
                cleaned_words.append(word)
            else:
                cleaned_words.append(re.sub(r'\s+', ' ', word).strip())

        # Rejoin and normalize
        subject = ' '.join(cleaned_words).lower().strip()
        
        return subject

    def analyze_sentiment(self, message_body):
        """
        Analyze the sentiment of the message body using both VADER and TextBlob.
        """
        if not message_body.strip():
            return 0  # Return neutral for empty messages

        # VADER Sentiment
        vader_score = self.analyzer.polarity_scores(message_body)['compound']

        # TextBlob Sentiment
        blob_sentiment = TextBlob(message_body).sentiment.polarity  # Range: [-1,1]

        # Average the two for better accuracy
        final_score = (vader_score + blob_sentiment) / 2
        return final_score
    
    def classify_sentiment(self, score):
        """
        Classify sentiment based on the score.
        """
        if score > 0.05:
            return 'positive'
        elif score < -0.05:
            return 'negative'
        else:
            return 'neutral'

    
    def parse(self, response):
        year_rows = response.xpath('//tr[th[contains(@colspan, "3")]]')

        for year_row in year_rows:
            year = year_row.xpath('th/text()').get().strip()

            if year != '2025':  # Corrected the comparison here
                self.logger.info(f"Skipping year: {year}")
                continue

            self.logger.info(f"Found year: {year}")

            month_rows = year_row.xpath('following-sibling::tr')
            months_data = []  # Initialize months_data here

            for month_row in month_rows:
                link = month_row.xpath('./th[@scope="row"]/a')
                href = link.xpath('./@href').get()
                month_year = link.xpath('./text()').get()

                if not href or not month_year:
                    continue

                try:
                    month_year_date = datetime.strptime(month_year, '%B %Y')
                except ValueError as e:
                    self.logger.error(f"Error parsing date '{month_year}': {e}")
                    continue

                if month_year_date < self.start_date or month_year_date > datetime.now():
                    self.logger.info(f"Skipping month: {month_year_date}")
                    continue
                months_data.append((month_year_date, href))

            # Now it's safe to sort months_data
            months_data.sort(key=lambda x: x[0])

            for month_year_date, href in months_data:
                full_url = response.urljoin(href)
                yield response.follow(full_url, self.parse_day)

    def parse_day(self, response):
        day_posts = response.xpath('//table[contains(@class, "thread-list")]//th/a/@href').extract()

        for post_link in day_posts:
            full_url = response.urljoin(post_link)
            yield response.follow(full_url, self.parse_thread)

        # Handle pagination
        next_page = response.xpath('//a[contains(text(), "Next")]/@href').get()
        if next_page:
            next_page_url = response.urljoin(next_page)
            self.logger.info(f"Following pagination: {next_page_url}")
            yield response.follow(next_page_url, self.parse_day)


    def identify_bug_keywords(self, thread):
        """
        Identify whether the thread contains bug-related content based on defined keywords.
        """
        closing_keywords = [
            "fixed", "resolved", "closed", "patch applied", "bug fixed", "issue resolved",
            "commit", "merged", "completed", "done", "solution provided", "solved", 
            "issue closed", "no further action", "finalized", "repaired", "problem solved",
            "concluded", "action completed", "status updated","more info in","worked","useful info",
            "closes the issue"
            ]

        # Keywords indicating the thread is open
        opening_keywords = [
            "reopen", "still an issue", "not fixed", "pending", "unresolved", "reopening",
            "not resolved", "not working", "needs attention", "to be fixed", "open",
            "follow up", "escalated", "waiting for response", "still open", "problem persists",
            "under investigation", "under review", "further action required", "issue not fixed"
        ]

        # Check if any of the messages contain closing or opening keywords
        closing_match = any(
            any(keyword.lower() in msg['Message_body'].lower() for keyword in closing_keywords)
            for msg in thread['Messages']
        )
        opening_match = any(
            any(keyword.lower() in msg['Message_body'].lower() for keyword in opening_keywords)
            for msg in thread['Messages']
        )
        
        # We classify as 'bug' if closing keywords are present, or if opening keywords are present with negative sentiment
        if closing_match:
            return 'bug_fixed'
        elif opening_match:
            sentiment_score = self.analyze_sentiment(thread['Messages'][-1]['Message_body'])
            if sentiment_score < -0.05:  # Negative sentiment threshold for bugs still open
                return 'bug_open'
        return 'non_bug'

    def update_thread_status(self, thread):
        """
        Determine the status of the thread based on keyword analysis, sentiment analysis, and time heuristics.
        """
        closing_keywords = {
            "fixed", "resolved", "closed", "patch applied", "bug fixed", "issue resolved",
            "commit", "merged", "completed", "done", "solution provided", "solved", 
            "issue closed", "no further action", "finalized", "repaired", "problem solved",
            "concluded", "action completed", "status updated","more info in","worked","useful info",
            "closes the issue"
        }

        opening_keywords = {
            "reopen", "still an issue", "not fixed", "pending", "unresolved", "reopening",
            "not resolved", "not working", "needs attention", "to be fixed", "open",
            "follow up", "escalated", "waiting for response", "still open", "problem persists",
            "under investigation", "under review", "further action required", "issue not fixed"
        }
        
        inactive_days = 60
        today = datetime.now()
        inactive_threshold = today - timedelta(days=inactive_days)

        messages = thread.get('Messages', [])
        if not messages:
            return 'unknown'

        # Filter valid messages
        valid_messages = [msg for msg in messages if msg.get('Date') and msg.get('Message_body')]
        if not valid_messages:
            return 'unknown'

        # Sort messages by date
        messages = sorted(valid_messages, key=lambda msg: msg['Date'])
        last_message = messages[-1]
        last_message_date = last_message['Date']

        # Ensure date format is correct
        if isinstance(last_message_date, str):
            last_message_date = datetime.strptime(last_message_date, '%Y-%m-%d %H:%M:%S')

        # Check thread activity
        is_active = last_message_date > inactive_threshold

        # Keyword Analysis
        subject = thread['Subject'].lower()
        message_bodies = [msg['Message_body'].lower() for msg in messages]

        closed_count = sum(
            keyword in subject or any(keyword in body for body in message_bodies)
            for keyword in closing_keywords
        )
        open_count = sum(
            keyword in subject or any(keyword in body for body in message_bodies)
            for keyword in opening_keywords
        )

        # Sentiment Analysis
        sentiment_scores = [self.analyze_sentiment(msg['Message_body']) for msg in valid_messages]
        overall_sentiment = sum(sentiment_scores) / len(sentiment_scores)
        overall_sentiment_category = self.classify_sentiment(overall_sentiment)

        last_message_sentiment = self.analyze_sentiment(last_message['Message_body'])
        last_message_sentiment_category = self.classify_sentiment(last_message_sentiment)

        # Decision Making (Combining All Factors)
        if closed_count > open_count and overall_sentiment_category == "positive" and last_message_sentiment_category == "positive":
            thread_status = "Closed"
        elif closed_count > open_count and overall_sentiment_category == "positive" and last_message_sentiment_category == "negative":
            thread_status = "Open"
        elif open_count > closed_count and overall_sentiment_category in {"negative", "neutral"} and last_message_sentiment_category in {"negative", "neutral"}:
            thread_status = "Open" if is_active else "Inactive"
        elif closed_count > 0 and open_count == 0 and not is_active:
            thread_status = "Closed"
        elif not is_active:
            if closed_count > 0 and open_count == 0:
                thread_status = "Closed"
            else:
                thread_status = "Inactive"
        else:
            thread_status = "Open"


        # Update thread in database
        self.collection.update_one({'_id': thread['_id']}, {'$set': {'Thread_Status': thread_status}})
        
        return thread_status


    def parse_thread(self, thread):
        messages=[thread]
        for response in messages:
            subject = response.xpath('//tr[th[contains(text(),"Subject:")]]/td/text()').get()
            sender = response.xpath('//tr[th[contains(text(),"From:")]]/td/text()').get()
            receiver = response.xpath('//tr[th[contains(text(),"To:")]]/td/text()').get()
            date = response.xpath('//tr[th[contains(text(),"Date:")]]/td/text()').get()

            message_id_href = response.xpath(
                '//tr[th[contains(text(),"Message-ID:")]]/td/a/@href'
            ).get()

            if message_id_href:
                # ✅ Take last part of URL & decode it (%40 → @, %3D → =, %2B → +)
                message_id = unquote(message_id_href.split('/')[-1])
            else:
                message_id = "Field Missing"

            if message_id in self.existing_message_ids:
                self.logger.info(f"Message with Message-ID {message_id} already exists.")
                continue

            
            message_content = response.xpath('//div[@class="message-content"]').get().strip()
            decoded_body = urllib.parse.unquote(message_content) if message_content else "No content"
            markdown_body = html2text.html2text(decoded_body,bodywidth=0)
            markdown_body = re.sub(r"#(\d+)", r"\#\1", markdown_body)#to remove the hyperlinking of github issue number in the content of the message

            # Extract attachments if available
            attachments = []
            attachment_rows = response.xpath('//table[@class="table table-sm table-responsive message-attachments"]//tbody/tr')

            if attachment_rows:
                for row in attachment_rows:
                    attachment_name = row.xpath('th/a/text()').get(default="Unknown")
                    attachment_url = row.xpath('th/a/@href').get(default="Unknown")
                    content_type = row.xpath('td[1]/text()').get(default="Unknown")
                    size = row.xpath('td[2]/text()').get(default="Unknown")
                    
                    if attachment_name != "Unknown":
                        attachments.append({
                            'Name': attachment_name,
                            'URL': response.urljoin(attachment_url),
                            'Content-Type': content_type,
                            'Size': size
                        })
            try:
                parsed_date = datetime.strptime(date.strip(), '%a, %d %b %Y %H:%M:%S')
            except ValueError:
                try:
                    parsed_date = datetime.strptime(date.strip(), '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    parsed_date = None

            formatted_date = parsed_date.strftime('%Y-%m-%d %H:%M:%S') if parsed_date else 'Field Missing'

            message_data = {
                'Subject': subject.strip() if subject else "Field Missing",
                'Sender': sender.strip() if sender else "Field Missing",
                'Receiver': receiver.strip() if receiver else "Field Missing",
                'Date': formatted_date,
                'Message_ID': message_id.strip() if message_id else "Field Missing",
                'Message_body': markdown_body,
                'Attachments': attachments if attachments else None,
            }

            def normalize_subject(subject):
                """
                Normalize the thread subject by removing all prefixes (like Re:, Fwd:, Bug Reappear:)
                while preserving 't:' if it exists in between.
                """
                # Define the reply prefixes pattern, allowing for variations and spaces
                reply_prefixes = (
                    r'^(?:'
                    r'(Re|Fwd|FW|Antwort|Antw|AW|Ynt|回复|答复|回复：|Re\[\d+\]|[EXT]|Bug\s*Reappear)'
                    r'[\s]*[:：]'      # Match ":" or "：" (Chinese colon)
                    r')+'
                )

                # Iteratively remove prefixes until none remain
                while re.match(reply_prefixes, subject, flags=re.IGNORECASE):
                    subject = re.sub(reply_prefixes, '', subject, flags=re.IGNORECASE).strip()

                # Ensure 't:' in between words is preserved
                words = subject.split()
                cleaned_words = []
                for word in words:
                    if word.lower() == "t:":
                        cleaned_words.append(word)
                    else:
                        cleaned_words.append(re.sub(r'\s+', ' ', word).strip())

                # Rejoin and normalize
                subject = ' '.join(cleaned_words).lower().strip()
                
                return subject


            # Create index on Normalized_Subject field if not already present
            existing_indexes = self.collection.index_information()
            if 'Normalized_Subject_1' not in existing_indexes:
                self.collection.create_index([("Normalized_Subject", pymongo.ASCENDING)])

            # Check for thread grouping based on normalized subject
            normalized_subject = normalize_subject(message_data['Subject'])
            if not normalized_subject:
                normalized_subject = "unknown-subject"

            # Try to find an existing thread using the normalized subject
            thread = self.collection.find_one({'Normalized_Subject': normalized_subject})

            if thread:
                thread_id = thread['_id']
                existing_message_ids = {msg['Message_ID'] for msg in thread['Messages']}  # Use set for faster lookup

                if message_id in existing_message_ids:
                    self.logger.info(f"Message with Message-ID {message_id} already exists in the thread.")
                    continue  # Skip if message is a duplicate

                # Add the new message to the existing thread
                self.collection.update_one(
                    {'_id': thread['_id']},
                    {
                        '$push': {
                            'Messages': {
                                '$each': [message_data],
                                '$sort': {'Date': 1}  # Ensure messages are sorted by date
                            }
                        }
                    }
                )
                # ✅ Recalculate thread status after adding a message
                updated_thread = self.collection.find_one({'_id': thread['_id']})
                updated_status = self.update_thread_status(updated_thread)

                self.logger.info(f"Thread {thread['_id']} status updated to {updated_status} after new message")

                self.existing_message_ids.add(message_id)  # Add new message to tracked set
                self.new_comments_count += 1  # Increment new comments count
                #update_github=True
            else:
                # Insert a new thread if no match found
                thread_id = self.collection.insert_one({
                    'Subject': message_data['Subject'],
                    'Normalized_Subject': normalized_subject,
                    'Messages': [message_data],
                    'Thread_Status': 'Open'  # New thread starts open
                }).inserted_id

                # Create a new thread object to pass to update_thread_status
                thread = {
                    '_id': thread_id,
                    'Subject': message_data['Subject'],
                    'Normalized_Subject': normalized_subject,
                    'Messages': [message_data]
                }

                # Update thread status immediately if needed
                self.logger.info(f"New thread created: {message_data['Subject']} - Initial Status: Open")
                self.new_issues_count += 1  # Increment new issues count
                #update_github=True
                # After adding all messages, update the thread status once
                updated_thread_status = self.update_thread_status(thread)

                # Efficient update: Directly update MongoDB without refetching
                self.collection.update_one(
                    {'_id': thread_id},
                    {'$set': {'Thread_Status': updated_thread_status}}
                )

                self.logger.info(f"Thread {thread_id} status updated to {updated_thread_status}")
    def _extract_message_id_from_comment(self, body):
        """
        Extract the clean Message-ID from a GitHub comment body.
        Handles cases with backticks, bold, angle brackets, or whitespace.
        """
        if not body:
            return None
        m = re.search(r"📮\s*Message\s*ID\s*:\s*`?<?([^`\s<>]+@[^`\s<>]+)>?`?", body, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip()
        return None
   
    def push_thread_to_github_bulk(self, threads):
        for thread in threads:
            #print(f"🔹 Checking thread: {thread.get('_id')}")
            #*****************
            if thread.get("github_pushed"):
                self.logger.info(f"⏩ Skipping already pushed thread {thread.get('_id')}")
                continue  # ✅ Skip if already pushed
            #**************
            if "Messages" in thread and isinstance(thread["Messages"], list):
                sorted_thread_messages = sorted(thread["Messages"], key=lambda msg: msg["Date"])
            else:
                print("❌ No messages found for thread!")
                self.logger.info("❌ No messages found for thread!")
                continue  # Skip processing if no messages exist

            main_message = sorted_thread_messages[0]  # First message is the main issue
            latest_thread_status = thread.get("Thread_Status", "Open").lower()  # Fetch latest status from MongoDB

            existing_issue = self.get_existing_github_issue(thread)

            if existing_issue:
                github_issue = existing_issue
                print(f"📌 Found existing GitHub issue #{github_issue.number}")
                self.logger.info(f"📌 Found existing GitHub issue #{github_issue.number}")
                # Update labels if needed
                current_labels = {label.name.lower() for label in github_issue.get_labels()}
                if latest_thread_status not in current_labels:
                    new_labels = [label for label in current_labels if label not in ["open", "closed"]]
                    new_labels.append(latest_thread_status)  # Add the correct status label
                    github_issue.edit(labels=new_labels)
                    print(f"✅ Updated labels for issue #{github_issue.number} → {new_labels}")
                    self.logger.info(f"✅ Updated labels for issue #{github_issue.number} → {new_labels}")
                    
                # ✅ **Update issue state based on Thread_Status**
                if latest_thread_status == "closed" and github_issue.state == "open":
                    github_issue.edit(state="closed")  # Close the issue
                    print(f"🔒 Issue #{github_issue.number} closed")
                    self.logger.info(f"🔒 Issue #{github_issue.number} closed")


                elif latest_thread_status == "open" and github_issue.state == "closed":
                    github_issue.edit(state="open")  # Reopen the issue
                    print(f"🔓 Issue #{github_issue.number} reopened")
                    self.logger.info(f"🔓 Issue #{github_issue.number} reopened")

            else:
                # Create issue if not found
                github_issue = self.create_github_issue(main_message, latest_thread_status)
                if github_issue:
                    self.collection.update_one(
                        {"_id": thread["_id"]},
                        {"$set": {"github_pushed": True, "github_issue_number": github_issue.number}}
                    )

                if not github_issue:
                    continue  # If issue creation fails, move to the next thread

            # Sync missing comments
            replies = sorted_thread_messages[1:]  
            #github_comments = list(github_issue.get_comments())
            #github_message_ids = {c.body.split("📮 Message ID:")[1].strip() for c in github_comments if "📮 Message ID:" in c.body}
            github_message_ids = set()
            for comment in github_issue.get_comments():  # PyGithub handles pagination
                mid = self._extract_message_id_from_comment(comment.body)
                if mid:
                    github_message_ids.add(mid)

            # From DB
            db_message_ids = {
                doc["message_id"]
                for doc in self.comments_collection.find({"github_issue_number": github_issue.number})
            }
            missing_comments = [msg for msg in replies if msg["Message_ID"] not in github_message_ids and msg["Message_ID"] not in db_message_ids]
            missing_comments.sort(key=lambda msg: msg['Date'])

            print(f"📌 Found {len(missing_comments)} missing comments for issue #{github_issue.number}")  
            self.logger.info(f"📌 Found {len(missing_comments)} missing comments for issue #{github_issue.number}")  
            for reply in missing_comments:
                self.add_github_comment(github_issue, reply)

            # Mark thread as pushed
            self.collection.update_one(
                {"_id": thread["_id"]}, 
                {"$set": {"github_pushed": True, "github_issue_number": github_issue.number}}
            )
            print(f"✅ Updated github_pushed=True for issue {github_issue.number}")
            self.logger.info(f"✅ Updated github_pushed=True for issue {github_issue.number}")


    def get_existing_github_issue(self, thread):
        # First, try the thread doc
        if "github_issue_number" in thread and thread["github_issue_number"]:
            return self.repo.get_issue(int(thread["github_issue_number"]))
        
        # Fallback: check all message_ids in this thread
        for msg in thread.get("Messages", []):
            mapping = self.comments_collection.find_one({"message_id": msg["Message_ID"]})
            if mapping and mapping.get("github_issue_number"):
                return self.repo.get_issue(int(mapping["github_issue_number"]))

        return None
    
    def create_github_issue(self, main_message, thread_status):
        """
        Create a GitHub issue for the main message of the thread.
        """
        print(f"mainmessage message id {main_message['Message_ID']}")
        self.logger.info(f"mainmessage message id {main_message['Message_ID']}")

        attachments_str = ""
        attachments = main_message.get('Attachments', [])
        if attachments:
            formatted_attachments = [
                f"- **{att.get('Name', 'Unknown')}**\n  - 📎 [Download]({att.get('URL', 'Unknown')})\n  - 📏 Size: {att.get('Size', 'Unknown')}"
                for att in attachments
            ]
            attachments_str = "\n".join(formatted_attachments)

        normalized_subject = self.normalize_subject(main_message['Subject'])
        issue_body = (
            f"**📨 Subject**: {main_message['Subject']}\n\n"
            f"**📅 Date:** {main_message['Date']}\n"
            f"**📤 Sender:** {main_message['Sender']}\n"
            f"**📥 Receiver:** {main_message['Receiver']}\n"
            f"**📮 Message ID:** `{main_message['Message_ID']}`\n\n"

            f"**📝 Message :**\n{main_message['Message_body']}\n"
        )

        if attachments_str:
            issue_body += f"\n\n**Attachments**:\n{attachments_str}"

        try:
            print(f"Creating new issue: {normalized_subject}")
            self.logger.info(f"Creating new issue: {normalized_subject}")
            issue = self.repo.create_issue(
                title=normalized_subject,
                body=issue_body,
                labels=["bug", thread_status]
            )

            self.logger.info(f"Issue created: {issue.html_url}")

            # ✅ Close issue immediately if thread_status is "closed"
            if thread_status == "closed":
                issue.edit(state="closed")
                print(f"🔒 Issue #{issue.number} was closed upon creation")
                self.logger.info(f"🔒 Issue #{issue.number} was closed upon creation")


            # Store the main issue in the comments collection
            self.comments_collection.insert_one({
                "subject": main_message['Subject'],
                "message_id": main_message['Message_ID'],
                "github_issue_number": issue.number,  
                "is_main_issue": True  
            })

            return issue
        except Exception as e:
            self.logger.error(f"Failed to create issue: {e}")
            return None

    def comment_exists_on_github(self, issue_number, message_id, github):
        """Check if a comment with the given Message-ID already exists on the GitHub issue."""
        issue = self.repo.get_issue(issue_number)
        for comment in issue.get_comments():
            extracted = self._extract_message_id_from_comment(comment.body)
            if extracted and extracted == message_id:
                return True
        return False

    def add_github_comment(self, issue, message):
        """
        Add a comment to the GitHub issue only if it is unique (based on Message_ID).
        """
        # 🔍 Check if message is already in the database AND exists on GitHub
        existing_comment = self.comments_collection.find_one(
            {"message_id": message['Message_ID'], "github_issue_number": issue.number}
        )
        if existing_comment:
            self.logger.info(f"⚠️ Comment {message['Message_ID']} already exists in MongoDB. Skipping.")
            return
        # ✅ Call comment_exists_on_github to check if the comment is already on GitHub
        if self.comment_exists_on_github(issue.number, message["Message_ID"], issue):
            #print(f"🚫 Comment {message['Message_ID']} already exists on GitHub. Skipping.")
            return  # ✅ Skip if the comment is already present

        print(f"✅ Adding comment for issue #{issue.number}: {message['Message_ID']}")  # Debugging line
        self.logger.info(f"✅ Adding comment for issue #{issue.number}: {message['Message_ID']}")  # Debugging line


        comment_body = (
            f"**📨 Subject:** {message['Subject']}\n\n\n"
            f"**📅 Date:** {message['Date']}\n"
            f"**📤 Sender:** {message['Sender']}\n"
            f"**📥 Receiver:** {message['Receiver']}\n"
            f"**📮 Message ID:** `{message['Message_ID']}`\n\n"
            f"**📝 Message:**\n{message['Message_body']}\n"
        )

        if message.get('Attachments'):
            attachments_str = "\n".join(
                f"- **{att.get('Name', 'Unknown')}**\n  - 📎 [Download]({att.get('URL', 'Unknown')})\n  - 📏 Size: {att.get('Size', 'Unknown')}"
                for att in message['Attachments']
            )
            comment_body += f"\n**Attachments:**\n{attachments_str}"

        try:
            issue.create_comment(body=comment_body)
            self.logger.info(f"✅ Added comment for issue #{issue.number}: {message['Message_ID']}")
             #Bump issue to top (reapply labels)
            current_labels = [label.name for label in issue.get_labels()]
            issue.edit(labels=current_labels)
            # ✅ Store the comment in MongoDB only after successful posting
            self.comments_collection.insert_one({
                "subject": message['Subject'],
                "message_id": message['Message_ID'],
                "github_issue_number": issue.number
            })

        except Exception as e:
            self.logger.error(f" Failed to add comment: {e}")
            print(f" Exception while adding comment: {e}")  # Debugging line
            self.logger.info(f" Exception while adding comment: {e}")  # Debugging line

    def fetch_sorted_threads(self):
        """
        Fetch threads sorted by the first message's date in ascending order.
        """
        return self.collection.aggregate([
            {
                "$addFields": {
                    "First_Message_Date": {
                        "$arrayElemAt": ["$Messages.Date", 0]  # Extract the first message's date
                    }
                }
            },
            {"$sort": {"First_Message_Date": 1}}  # Sort by first message date (oldest first)
        ])

    def close(self, reason):
        """
        When the spider finishes, process all threads and update GitHub issues.
        """
        self.logger.info(f"New issues created: {self.new_issues_count}")
        self.logger.info(f"New comments added: {self.new_comments_count}")
        threads = self.fetch_sorted_threads()
        self.push_thread_to_github_bulk(threads)
        
    