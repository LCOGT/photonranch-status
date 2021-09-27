import json, os, boto3, decimal, sys, ulid, logging, time, datetime
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError

from helpers import _get_response, _get_body, DecimalEncoder, _empty_strings_to_dash
from helpers import *

"""
TODO:
- auth guard for posting status
- clean 'get_all_site_open_status' method
- clean env variable loading and aws resource connecting

"""

dynamodb = boto3.resource('dynamodb')

try:
    status_table = dynamodb.Table(os.getenv('STATUS_TABLE'))
except Exception as e:
    print(e)


def stream_handler(event, context):
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
    ''' 
    {'status_type': 'devicesStatus', 'status': {...}}
    '''

    # We want to update the existing status with new values in the incoming status. 
    existing_status = get_status(site, status_type).get("status", {})
    merged_status = { **existing_status, **new_status}

    entry = {
        "site": site,    
        "statusType": status_type,
        "status": merged_status,
        "server_timestamp_ms": int(time.time() * 1000),
    }
    dynamodb_entry = _empty_strings_to_dash(entry)

    # Convert floats into decimals for dynamodb
    dynamodb_entry = json.loads(json.dumps(dynamodb_entry, cls=DecimalEncoder), parse_float=decimal.Decimal)

    table_response = status_table.put_item(Item=dynamodb_entry)
    return table_response


def get_status(site, status_type):
    table_response = status_table.get_item(Key={"site": site, "statusType": status_type})
    return table_response.get("Item", {})


def get_combined_site_status(site):
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

    # Check that all required keys are present.
    required_keys = ['statusType', 'status']
    actual_keys = body.keys()
    for key in required_keys:
        if key not in actual_keys:
            print(f"Error: missing requied key {key}")
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


def get_site_device_status(event, context):
    """ Return the full status for the requested site """
    site = event['pathParameters']['site']
    status = get_status(site, "deviceStatus")
    return _get_response(200, status)


def get_site_wx_enc_status(event, context):
    site = event['pathParameters']['site']
    status = get_status(site, "wxEncStatus")
    return _get_response(200, status)


def get_site_complete_status(event, context):
    """ Return the full status for the requested site """
    if event['pathParameters']['site'] == '':
        return _get_response(400, 'Site not provided.')
    site = event['pathParameters']['site']
    status = get_combined_site_status(site)
    return _get_response(200, status)


def clear_all_site_status(event, context):
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
    #status_table = dynamodb.Table('photonranch-status')
    allOpenStatus = {}
    trues = ['Yes', 'yes', 'True', 'true', True]
    falses = ['No', 'no', 'False', 'false', False]
    time_now = time.time()
    response = status_table.scan()
    for stat in response['Items']:

        site = stat['site'] 
        allOpenStatus[site] = {}
        status_age_s = int(time_now - float(stat['server_timestamp_ms'])/1000)
        allOpenStatus[site]['status_age_s'] = status_age_s

        # Handle the sites that don't have weather status
        try:
            weather_key = list(stat['status']['observing_conditions'])[0]
            weather_status = stat['status']['observing_conditions'][weather_key]
            # Handle case where weather station exists but has no status
            if weather_status is None: 
                raise Exception('No weather status')
        except Exception as e:
            print(e)
            print(f"Site {site} probably does not have a weather station")
            allOpenStatus[site]['hasWeatherStatus'] = False
            continue

        # We care mainly about 'weather_ok' and 'open_ok'.
        allOpenStatus[site]['hasWeatherStatus'] = True
        allOpenStatus[site]['weather_ok'] = weather_status.get('wx_ok', False) in trues
        allOpenStatus[site]['open_ok'] = weather_status.get('open_ok', False) in trues

    return _get_response(200, allOpenStatus)


if __name__=="__main__":
    print('hello')
    table = dynamodb.Table('photonranch-status-dev')
    stat = table.get_item(Key={"site": "mrc", "statusType": "deviceStatus"})
    upload = stat['Item']
    print(upload['status'].keys())
    upload['status'].pop('enclosure')
    print(upload['status'].keys())
    #print(table.put_item(Item=upload))

    #table.delete_item(Key={"site": "test", "statusType": "deviceStatus"})
    site = 'tst'
    all_status_entries = table.scan(
        FilterExpression = Attr('site').eq(site)
    )
    for item in all_status_entries['Items']:
        table.delete_item(Key={
            "site": item['site'],
            "statusType": item['statusType']
        })
