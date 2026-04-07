import logging
from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings
from Automation import PgsqlBugSpider

logging.basicConfig(
    filename="automation_run.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

if __name__ == "__main__":
    process = CrawlerProcess()
    process.crawl(PgsqlBugSpider)
    process.start()
    logging.info("🏁 Automation run completed successfully.")
