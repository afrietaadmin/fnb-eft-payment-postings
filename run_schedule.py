import os
import time
import schedule
import datetime
import subprocess
import sys
from dotenv import load_dotenv

load_dotenv('/srv/applications/fnb_EFT_payment_postings/.env')

BASE_DIR = '/srv/applications/fnb_EFT_payment_postings'
FETCH_SCRIPT = os.path.join(BASE_DIR, 'scripts/fetch_fnb_transactions.py')
SANITIZE_SCRIPT = os.path.join(BASE_DIR, 'scripts/sanitize_data.py')
POST_SCRIPT = os.path.join(BASE_DIR, 'scripts/post_payments_UISP.py')
TELEGRAM_NOTIFIER_SCRIPT = os.path.join(BASE_DIR, 'telegram_notifier.py')

SCRIPTS_TO_RUN = [FETCH_SCRIPT, SANITIZE_SCRIPT, POST_SCRIPT, TELEGRAM_NOTIFIER_SCRIPT]
PYTHON_EXECUTABLE = os.path.join(BASE_DIR, 'venv/bin/python')

def run_script(script):
    try:
        print(f'Running {os.path.basename(script)}...')
        result = subprocess.run([PYTHON_EXECUTABLE, script], capture_output=True, text=True, env=os.environ)
        if result.returncode != 0:
            print(f'Error in {script}: {result.stderr}')
        else:
            print(f'Completed {os.path.basename(script)}')
    except Exception as e:
        print(f'Exception running {script}: {e}')

def run_scripts():
    now = datetime.datetime.now()
    if now.weekday() == 6:
        print('Skipping Sunday')
        return

    print(f'Running scheduled tasks at {now}')
    for script in SCRIPTS_TO_RUN:
        run_script(script)

def setup_schedule():
    for hour in range(6, 19, 2):
        schedule.every().day.at(f'{hour:02d}:00').do(run_scripts)
    print('Scheduler started')

if __name__ == '__main__':
    setup_schedule()
    print('First run on startup')
    run_scripts()

    while True:
        schedule.run_pending()
        time.sleep(60)
