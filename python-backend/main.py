from datetime import datetime
from flask import Flask, request
from flask_caching import Cache
from flask_cors import CORS
import json
from auction_data_aggregator import AuctionDataAggregator
from auction_data_fetcher import AuctionDataFetcher
from local_storage_manager import LocalStorageManager
from mongodb_manager import MongoDBManager
import schedule
import threading
import time
import socket
from waitress import serve

app = Flask(__name__)
CORS(app)
cache = Cache(app, config={'CACHE_TYPE': 'simple'})
auction_fetcher = AuctionDataFetcher()
data_aggregator = AuctionDataAggregator()
db_manager = MongoDBManager()
#db_manager = LocalStorageManager()

def fetch_auction_data():
    print("Fetching auction data...")
    result = auction_fetcher.run()

    if result is not None:
        print("Data fetched successfully. Saving to database.")
        db_manager.save_latest_item_prices(result)

        for entry in result['data']:
            # Convert given timestamp to datetime and adjust to the start of the hour
            timestamp_dt = datetime.utcfromtimestamp(result['timestamp'] / 1000)
            timestamp_dt = timestamp_dt.replace(minute=0, second=0, microsecond=0)
            timestamp_adjusted = int(timestamp_dt.timestamp() * 1000)
            # check if we should save the total costs
            total_costs_exists = db_manager.check_timestamp_exists_in_total_costs(entry['region'], timestamp_adjusted)
            print(f"Checking if total costs exists for {entry['region']} on {timestamp_adjusted}: {total_costs_exists}")
            data_with_timestamp = {
                'timestamp': timestamp_adjusted,
                'total_cost': entry['data']['price']
            }
            if not total_costs_exists:
                data_with_timestamp = {
                    'timestamp': timestamp_adjusted,
                    'total_cost': entry['data']['price']
                }
                print(f"Saving total costs for {entry['region']} on {timestamp_adjusted}: {entry['data']['price']}")
                db_manager.save_total_costs(entry['region'], data_with_timestamp)

            # check if we should calculate yesterdays daily average
            date = datetime.fromtimestamp(result['timestamp'] / 1000 - 86400).date()
            daily_average_exists = db_manager.check_date_exists_in_daily_average(entry['region'], date.strftime('%Y-%m-%d'))
            print(f"Checking if daily average exists for {entry['region']} on {date.strftime('%Y-%m-%d')}: {daily_average_exists}")
            if not daily_average_exists:
                previous_data = db_manager.get_total_costs_from_previous_day(entry['region'], result['timestamp'])
                daily_averages = data_aggregator.aggregate_daily_averages(previous_data)
                print(f"Saving daily average for {entry['region']} on {date.strftime('%Y-%m-%d')}: {daily_averages}")
                if daily_averages:
                    for daily_average in daily_averages:
                        db_manager.save_daily_average(entry['region'], daily_average)

    cache.clear()
    print("Auction data fetched successfully")

# Schedule the task to run every hour
schedule.every().hour.do(fetch_auction_data)

# Create a separate thread to execute the scheduled tasks
def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(1)

@app.route('/api/data/current', methods=['GET'])
def get_current_data():
    print("Fetching current data...")
    cache_key = 'current_data'
    data = cache.get(cache_key)
    if data is None:
        print("Cache missing. Getting data from db.")
        data = db_manager.get_latest_item_prices()
        data = json.dumps(data, default=str)
        cache.set(cache_key, data, timeout=None)
    else:
        print("Returning cached current data")
    return data


@app.route('/api/data/history', methods=['GET'])
def get_history_data():
    print("Fetching history data...")
    cache_key = 'history_data'
    data = cache.get(cache_key)
    if data is None:
        print("Cache missing. Getting data from db.")
        data = db_manager.get_all_daily_averages()
        data = json.dumps(data, default=str)
        cache.set(cache_key, data, timeout=None)
    else:
        print("Returning cached current data.")
    return data

def get_local_ip():
    """Function to get the local IP address of the machine."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't even have to be reachable
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '0.0.0.0'
    finally:
        s.close()
    return IP

if __name__ == '__main__':
    print("Starting Flask app")
    # Start the scheduler thread
    fetch_auction_data()
    print("Auction data fetched successfully")
    scheduler_thread = threading.Thread(target=run_scheduler)
    scheduler_thread.start()

    # Start the Flask app using the local IP address
    print(get_local_ip())
    local_ip = '0.0.0.0'
    port = 5000
    print("Flask app starting")
    print(f"http://{local_ip}:{port}/api/data/current")
    print(f"http://{local_ip}:{port}/api/data/history")
    #app.run(host=local_ip)
    serve(app, host=local_ip, port=port)
