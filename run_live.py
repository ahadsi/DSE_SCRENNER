import subprocess, sys, time
from database import init_db, get_status
from db_tools import guard_and_backup

guard_and_backup()   # backup once/day + row-count guard; never deletes market data
init_db()
collector=subprocess.Popen([
    sys.executable,'dse_collector.py','--bootstrap','--history-days','320','--interval','120'
])

try:
    print("LIVE DSE collector started.")
    print("Waiting for first live snapshot...")
    deadline=time.time()+90
    while time.time()<deadline:
        if get_status('last_success'):
            print("LIVE snapshot received successfully.")
            break
        if collector.poll() is not None:
            print("Collector stopped. Check collector error above.")
            break
        time.sleep(2)

    print("Fast-start: loading historical OHLCV in monthly chunks for EMA200/indicators...")
    last_msg=0
    while not get_status('history_bootstrapped_at'):
        if collector.poll() is not None:
            print("Collector stopped before historical bootstrap completed.")
            break
        state = get_status('history_bootstrap_state', '')
        err = get_status('history_bootstrap_error', '')
        if state == 'FAILED' and err:
            print(f"Historical bootstrap FAILED: {err}")
            print("Scanner will not wait forever. Check the last History chunk error and try again later.")
            break
        if time.time()-last_msg>15:
            if state:
                print(f"History status: {state}. Historical data is being cached locally...")
            else:
                print("History still loading... waiting for the first historical chunk.")
            last_msg=time.time()
        time.sleep(3)

    if get_status('history_bootstrapped_at'):
        print("Historical data ready. Starting live scanner...")
    else:
        print("Historical data is not ready; scanner remains in WARMING_UP mode. See history_bootstrap_error in db/dse_live.db status.")

    while True:
        subprocess.run([sys.executable,'live_scanner.py','--once','--limit','30'])
        time.sleep(120)

except KeyboardInterrupt:
    print("\nStopping DSE Smart Scanner...")
finally:
    if collector.poll() is None:
        collector.terminate()
        try: collector.wait(timeout=10)
        except subprocess.TimeoutExpired: collector.kill()
