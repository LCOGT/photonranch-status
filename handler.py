import json, os, boto3, decimal, time
from boto3.dynamodb.conditions import  Attr
from datetime import datetime, timedelta

from helpers import _get_response 
from helpers import _get_body 
from helpers import DecimalEncoder
from helpers import _empty_strings_to_dash
from helpers import send_to_datastream
from helpers import add_item_timestamps
from helpers import merge_dicts

"""
TODO:
- auth guard for posting status
- clean env variable loading and aws resource connecting

"""

dynamodb = boto3.resource('dynamodb')

try:
    status_table = dynamodb.Table(os.getenv('STATUS_TABLE'))
    status_table = dynamodb.Table()
except Exception as e:
    print(e)

# Use local dynamodb if running with serverless-offline
if os.getenv('IS_OFFLINE'):
    print("In offline development mode: " + os.getenv('IS_OFFLINE'))
    resource = boto3.resource('dynamodb', endpoint_url='http://localhost:9000')
    status_table = resource.Table(name='photonranch-status-dev')


def stream_handler(event, context):
    """Sends the site status event to datastream."""
    print(f"size of stream event: {len(event['Records'])}")
    print(json.dumps(event))
    records = event.get('Records', [])
    for item in records:

        site = item['dynamodb']['Keys']['site']['S']
        status_type = item['dynamodb']['Keys']['statusType']['S']

        status = get_status(site, status_type)

        # If the status we fetched doesn't have the key 'status', then there is no data so we should close the handler.
        if status.get('status', 'not here') == 'not here': 
            return

        # Send to datastreamer
        send_to_datastream(site, status) 

    return _get_response(200, "stream has activated this function")


#=========================================#
#=======     Status CRUD Methods    ======#
#=========================================#

def post_status(site, status_type, new_status):
    """Add timestamps to the status and apply the updates to the entry in DynamoDB.

    Args:
        site (str): site abbreviation, used as partition key in DynamoDB table
        status_type (str): weather | enclosure | device, used as the sort key in DynamoDB
        new_status (dict): this is the dict of new status values to apply. It should have the format:
        
        new_status = {
            "device_type": {
                "device_type_instance_name": {
                    "key1": "val1",
                    "key2": "val2",
                    ...
                },
                ...
            },
            ...
        }

    Returns:
        dict: dynamodb put_item response
    """

    server_timestamp_ms = int(time.time() * 1000)

    # Add timestamps to the status items
    new_status_with_timestamps = add_item_timestamps(new_status, server_timestamp_ms)

    # We want to update the existing status with new values in the incoming status. 
    existing_status = get_status(site, status_type).get("status", {})
    merged_status = merge_dicts(existing_status, new_status_with_timestamps)

    entry = {
        "site": site,    
        "statusType": status_type,
        "status": merged_status,
        "server_timestamp_ms": server_timestamp_ms,
    }
    dynamodb_entry = _empty_strings_to_dash(entry)

    # Convert floats into decimals for dynamodb
    dynamodb_entry = json.loads(json.dumps(dynamodb_entry, cls=DecimalEncoder), parse_float=decimal.Decimal)

    table_response = status_table.put_item(Item=dynamodb_entry)
    return table_response

def post_forecast_status(site, status_type, new_status):
    """Add timestamps to the forecast status, combines it with forecast data already in dynamodb up to a data period

    Args:
        site (str): site abbreviation, used as partition key in DynamoDB table
        status_type (str): forecast
        new_status (dict): this is the dict of new status values to apply

    Returns:
        dict: dynamodb put_item response
    """
    # Add timestamps to the status items
    server_timestamp_ms = int(time.time() * 1000)
    existing_status = get_status(site, status_type).get("status", {})

    merged_forecast = existing_status.get("forecast", []) + new_status.get("forecast", [])
    print("Existing Forecast Length:", len(existing_status.get("forecast", [])))
    print("New Forecast Length:", len(new_status.get("forecast", [])))
    print("Merged Forecasts Length:", len(merged_forecast))

    # Variable for how far in the past we save forecast data
    forecast_data_period = timedelta(hours=96)
    
    # Filter out report objects that are older than the data retention period
    filtered_merged_forecast = [report for report in merged_forecast if (datetime.utcnow().astimezone() - datetime.fromisoformat(report.get("utc_long_form", ""))) <= forecast_data_period]

    print("Post Filter time length: ", len(filtered_merged_forecast))
    print(', '.join(report.get("utc_long_form", "missing") for report in filtered_merged_forecast))

    # Removing report duplicates based on utc time
    seen_time_reports = set()
    unique_filtered_merged_forecast = []
    for report in filtered_merged_forecast:
        if report.get("utc_long_form" , "") not in seen_time_reports:
            unique_filtered_merged_forecast.append(report)
            seen_time_reports.add(report.get("utc_long_form" , ""))

    print("Post Duplicate removal length:", len(unique_filtered_merged_forecast))
    print(', '.join(report.get("utc_long_form", "missing") for report in filtered_merged_forecast))

    merged_status = existing_status
    merged_status["forecast"] = unique_filtered_merged_forecast

    entry = {
        "site": site,
        "statusType": status_type,
        "status": merged_status,
        "server_timestamp_ms": server_timestamp_ms,
    }
    dynamodb_entry = _empty_strings_to_dash(entry)

    # Convert floats into decimals for dynamodb
    dynamodb_entry = json.loads(json.dumps(dynamodb_entry, cls=DecimalEncoder), parse_float=decimal.Decimal)

    table_response = status_table.put_item(Item=dynamodb_entry)
    return table_response

def get_status(site, status_type):
    """Retrieves status from table for a given site and status type."""
    table_response = status_table.get_item(Key={"site": site, "statusType": status_type})
    if(status_type == 'forecast'):
        print("get_status() forecast response length", len(table_response.get("Item" , {}).get("status").get("forecast")))
        print(', '.join(report.get("utc_long_form") for report in table_response.get("Item" , {}).get("status").get("forecast")))
    return table_response.get("Item", {})


def get_combined_site_status(site):
    """Retrieves and combines status of all status types (weather, enclosure, device) for a given site."""
    all_status_entries = status_table.scan(
        FilterExpression = Attr('site').eq(site)
    )
    combined_status = {}
    status_age_timestamps = {}
    latest_timestamp = 0
    for item in all_status_entries['Items']:
        combined_status = dict(combined_status, **item.get('status', {})) 
        status_age_timestamps[item.get('statusType')] = item.get('server_timestamp_ms')
        latest_timestamp = max(float(item.get("server_timestamp_ms", 0)), latest_timestamp)
    return {
        "site": site,
        "statusType": "combined",
        "latest_status_timestamp_ms": latest_timestamp,
        "status_age_timestamps_ms": status_age_timestamps,
        "status": combined_status
    }


#=========================================#
#=======       API Endpoints      ========#
#=========================================#

def post_status_http(event, context):
    '''Updates a site's status with a regular http request.
    Example request body: {'statusType': 'devicesStatus', 'status': {...}}
    '''
    body = _get_body(event)
    site = event['pathParameters']['site']

    print(f"site: {site}")
    print("body: ", body)

    # Check that all required keys are present.
    required_keys = ['statusType', 'status']
    actual_keys = body.keys()
    for key in required_keys:
        if key not in actual_keys:
            print(f"Error: missing required key {key}")
            return {
                "statusCode": 400,
                "body": f"Error: missing required key {key}",
                "headers": {
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Credentials": "true",
                },
            }
    
    # forecast statusType being handled uniquely
    if body['statusType'] == 'forecast':
        response = post_forecast_status(site, body['statusType'], body['status'])
    else:
        response = post_status(site, body['statusType'], body['status'])

    return _get_response(200, response)


def get_site_status(event, context):
    """Return the status for the requested site and status type."""
    site = event['pathParameters']['site']
    status_type = event['pathParameters']['status_type']
    status = get_status(site, status_type)
    return _get_response(200, status)


def get_site_complete_status(event, context):
    """Return the full status for the requested site."""
    if event['pathParameters']['site'] == '':
        return _get_response(400, 'Site not provided.')
    site = event['pathParameters']['site']
    status = get_combined_site_status(site)
    return _get_response(200, status)


def clear_all_site_status(event, context):
    """Remove all status entries for the requested site."""
    site = event['pathParameters']['site']
    all_status_entries = status_table.scan(
        FilterExpression = Attr('site').eq(site)
    )
    items_removed = []
    for item in all_status_entries['Items']:
        response = status_table.delete_item(Key={
            "site": item['site'],
            "statusType": item['statusType']
        })
        items_removed.append(response)
    return _get_response(200, {"items_removed": items_removed})


def get_all_site_open_status(event, context):
    """Creates a dictionary of sites with true/false value describing weather ok to open.
    
    Returns:
        all_open_status (dict): dictionary of sites with "wx_ok" set as a true/false value 
        describing weather ok to open, and with "status_age_s" of all status types set to
        the difference between the status time and current time in seconds.

        Output should have a dict with sites as keys and values similar to
        {
            'device': {'status_age_s': 250096},
            'enclosure': {'status_age_s': 250062},
            'weather': {'status_age_s': 250064},
            'wx_ok': True
        }
        """
        
    all_open_status = {}
    possible_trues = ['Yes', 'yes', 'True', 'true', True]
    possible_falses = ['No', 'no', 'False', 'false', False]
    time_now = time.time()

    # Get all entries in the dynamodb status table
    response = status_table.scan()

    for status_entry in response['Items']:

        site = status_entry['site'] 
        status_type = status_entry['statusType']
        server_timestamp_ms = status_entry['server_timestamp_ms']
        status = status_entry['status']

        if site not in all_open_status:
            all_open_status[site] = {}

        all_open_status[site][status_type] = {
           "status_age_s": int(time_now - (float(server_timestamp_ms) / 1000))
        }

        # Try to add the wx_ok key, but skip if it's not available.
        if status_entry['statusType'] == 'weather' and 'observing_conditions' in status_entry['status']:
            try:
                # Get the name of the weather status device (assume there is just one). This is needed in the line
                # below to get the weather values from this device. 
                weather_key = list(status_entry['status']['observing_conditions'])[0] 
                weather_status = status_entry['status']['observing_conditions'][weather_key]

                # Convert the wx_ok value from a string to a boolean, accounting for a variety of possible truthy values
                # as specified by Wayne.
                wx_ok = weather_status['wx_ok']['val'] in possible_trues

                # If no problems till now, add the wx_ok key to our response payload.
                all_open_status[site]['wx_ok'] = wx_ok
            except: 
                # One possible reason for failure: a site reports an empty status value under "observing_conditions"
                print(f"Warning: failed to get wx_ok status for site {site}")

    return _get_response(200, all_open_status)
