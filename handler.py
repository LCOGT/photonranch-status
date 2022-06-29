import json, os, boto3, decimal, time
from boto3.dynamodb.conditions import  Attr

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
except Exception as e:
    print(e)


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
    """Add timestamps to the status and apply the updates to the entry in dynamodb.

    Args:
        site (str): site abbreviation, used as partition key in dynamodb table
        status_type (str): weather | enclosure | device, used as the sort key in dynamodb
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


def get_status(site, status_type):
    """Retrieves status from table for a given site and status type."""
    table_response = status_table.get_item(Key={"site": site, "statusType": status_type})
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
    ''' 
    Update a site's status with a regular http request.
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
    "Remove all status entries for the requested site."
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
        the difference between the status time and current time in seconds."""
        
    all_open_status = {}
    trues = ['Yes', 'yes', 'True', 'true', True]
    falses = ['No', 'no', 'False', 'false', False]
    time_now = time.time()
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

        if status_entry['statusType'] == 'weather' and 'observing_conditions' in status_entry['status']:
            weather_key = list(status_entry['status']['observing_conditions'])[0]
            weather_status = status_entry['status']['observing_conditions'][weather_key]
            wx_ok = weather_status.get('wx_ok', {'val': False}).get('val') in trues
            all_open_status[site]['wx_ok'] = wx_ok

    return _get_response(200, all_open_status)

    
if __name__=="__main__":
    print('hello')
    table = dynamodb.Table('photonranch-status-dev')
    stat = table.get_item(Key={"site": "tst", "statusType": "weather"})
    print(stat)
    upload = stat['Item']
    print(upload['status'].keys())

    from pprint import pprint
    status_table = table
    pprint(get_all_site_open_status({},{}))

    #upload['status'].pop('enclosure')
    #print(upload['status'].keys())
    #print(table.put_item(Item=upload))

    #table.delete_item(Key={"site": "test", "statusType": "deviceStatus"})
    #site = 'tst'
    #all_status_entries = table.scan(
        #FilterExpression = Attr('site').eq(site)
    #)
    #for item in all_status_entries['Items']:
        #table.delete_item(Key={
            #"site": item['site'],
            #"statusType": item['statusType']
        #})
