# 🚀 Automated Centralized GitHub Repository for PostgreSQL Bugs

![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)
![Scrapy](https://img.shields.io/badge/Scrapy-Web%20Scraping-green?logo=scrapy)
![MongoDB](https://img.shields.io/badge/MongoDB-Database-green?logo=mongodb)
![GitHub](https://img.shields.io/badge/GitHub-API-black?logo=github)
![Cron](https://img.shields.io/badge/Cron-Automation-orange)
![Status](https://img.shields.io/badge/Status-Production%20Ready-success)

---

## 📌 Project Overview

This project automates the process of:

* 🐞 Scraping PostgreSQL bugs from mailing lists
* 🧠 Analyzing bug discussions using **sentiment analysis + keyword matching**
* 🗄️ Storing structured data in MongoDB
* 📤 Creating and updating GitHub Issues automatically
* ⏰ Running fully automated using Cron jobs

---

## 🏗️ Project Structure

```
Automation/
│
├── spiders/
│   ├── Automation.py                # Main Scrapy spider
│   ├── run_pgsql_automation.py     # Runner script
│   └── __init__.py
│
├── settings.py
├── items.py
├── pipelines.py
├── middlewares.py
│
├── requirements.txt
└── README.md
```

---

## ⚙️ Technologies Used

| Technology    | Purpose                |
| ------------- | ---------------------- |
| Python 3.12   | Core programming       |
| Scrapy        | Web scraping framework |
| MongoDB       | Data storage           |
| PyMongo       | MongoDB integration    |
| BeautifulSoup | HTML parsing           |
| Requests      | HTTP handling          |
| PyGithub      | GitHub API integration |
| TextBlob      | Sentiment analysis     |
| VADER         | Sentiment analysis     |
| Cron          | Task scheduling        |

---

## 🧠 Intelligent Bug Classification

This project uses a **hybrid approach**:

### 🔍 Keyword Matching

* Detects words like: `fixed`, `resolved`, `failed`, `error`

### 📊 Sentiment Analysis

* Uses:

  * TextBlob
  * VADER

### 🧩 Final Classification

* ✅ Open
* ❌ Closed
* ⚠️ Inactive

---

## 🚀 Setup Instructions (VM Deployment)

---

### 🔹 Step 1: Clone Repository

```bash
git clone https://github.com/BharatDBPG/Automated-centralized-github-repository-for-Postgresql-Bugs.git
cd Automated-centralized-github-repository-for-Postgresql-Bugs
```

---

### 🔹 Step 2: Create Virtual Environment

```bash
python3 -m venv automation_env
source automation_env/bin/activate
```

---

### 🔹 Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

---

### 🔹 Step 4: Download TextBlob Data

```bash
python -m textblob.download_corpora
```

---

### 🔹 Step 5: Setup MongoDB

Ensure MongoDB is running:

```bash
sudo systemctl start mongod
sudo systemctl enable mongod
```

---

### 🔹 Step 6: Set GitHub Token

```bash
export GITHUB_TOKEN=your_token_here
```

---

## ▶️ Manual Execution

---

### 🐞 Run Bug Automation

```bash
cd Automation/spiders
python run_pgsql_automation.py
```

---

### ✅ Expected Output

* MongoDB updated
* GitHub Issues created
* Logs generated

---

## ⏰ Automation Using Cron

---

### Open crontab

```bash
crontab -e
```

---

### Add the following:

```bash
GITHUB_TOKEN=your_token_here
PYTHONPATH=/home/cloud/git_pgsql_mailing_list/Automation

0 10 * * * cd /home/cloud/git_pgsql_mailing_list/Automation/spiders && /home/cloud/automation_env/bin/python run_pgsql_automation.py >> /home/cloud/git_pgsql_mailing_list/bugs.log 2>&1
```

---

### 🕒 Schedule

| Task        | Time           |
| ----------- | -------------- |
| Bug Scraper | 10:00 AM daily |

---

## 📄 Logs

Logs are stored at:

```
/home/cloud/git_pgsql_mailing_list/bugs.log
```

To monitor:

```bash
tail -f bugs.log
```

---

## ⚠️ Troubleshooting

---

### ❌ Module Not Found

```bash
pip install -r requirements.txt
```

---

### ❌ GitHub Token Missing

```bash
export GITHUB_TOKEN=your_token
```

---

### ❌ MongoDB Not Connecting

```bash
sudo systemctl status mongod
```

---

### ❌ Cron Not Running

```bash
crontab -l
service cron status
```

---

## 🔐 Security Notes

* Never commit your GitHub token
* Use environment variables
* Restrict token permissions

---

## 🏁 Final Outcome

✅ Fully automated bug tracking system
✅ Centralized GitHub issue creation
✅ Intelligent classification
✅ VM-based execution
✅ Production-ready setup

---

## 👨‍💻 Maintainer

**BharatDB Team**

---

## ⭐ Support

If this project helps you:

👉 Star the repository
👉 Share with your team

---

💡 *Designed for scalable and automated PostgreSQL bug tracking*
 **VASUKI M**

---

