import json, os, boto3, decimal, sys, ulid, logging, time, datetime
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError

from helpers import _get_response, _get_body, DecimalEncoder, _empty_strings_to_dash
from helpers import *

"""
TODO:
- auth guard for posting status
- clean 'getAllSiteOpenStatus' method
- clean env variable loading and aws resource connecting

"""

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

dynamodb = boto3.resource('dynamodb')

try:
    status_table = dynamodb.Table(os.getenv('STATUS_TABLE'))
    subscribers_table = dynamodb.Table(os.getenv('STATUS_CONNECTION_TABLE'))
    WSS_URL = os.getenv('WSS_URL')
except Exception as e:
    print(e)


QUEUE_URL = os.getenv('QUEUE_URL')
SQS = boto3.client('sqs')


def connection_manager(event, context):
    """
    Handles connecting and disconnecting for the Websocket
    """
    connection_id = event["requestContext"].get("connectionId")

    if event["requestContext"]["eventType"] == "CONNECT":
        logger.info("Connect requested")

        # Check that the subscriber specified which site they are subscribed to.
        try:
            site = event["queryStringParameters"]["site"]
        except:
            return _get_response(400, "No site specified")

        # Add connection_id to the database
        add_connection(connection_id, site)
        return _get_response(200, "Connect successful.")

    elif event["requestContext"]["eventType"] in ("DISCONNECT", "CLOSE"):
        logger.info("Disconnect requested")
        
        # Remove the connection_id from the database
        subscribers_table.delete_item(Key={"ConnectionID": connection_id}) 
        remove_connection(connection_id)
        return _get_response(200, "Disconnect successful.")

    else:
        logger.error("Connection manager received unrecognized eventType '{}'")
        return _get_response(500, "Unrecognized eventType.")


def streamHandler(event, context):
    print(f"size of stream event: {len(event['Records'])}")
    print(json.dumps(event))
    #data = event['Records'][0]['dynamodb']['NewImage']
    records = event.get('Records', [])
    for item in records:

        site = item['dynamodb']['Keys']['site']['S']
        status_type = item['dynamodb']['Keys']['statusType']['S']

        status = getStatus(site, status_type)

        # If the status we fetched doesn't have the key 'status', then there is no data so we should close the handler.
        # Note: using context.succeed() prevents the dynamodb stream from continuously retrying a bad event
        if status.get('status', 'not here') == 'not here': 
            context.succeed()

        connection_ids = get_connection_ids(site)

        # Break the list of connection IDs into a list of lists of connection IDs 
        # ie. from [1,2,3,4,5] to [[1,2], [3,4], [5]] using a chunk size of 2
        # This is so lambda functions sending data to clients can run in parallel with managable loads.
        chunk_size = 10
        chunked_connection_ids = [connection_ids[i:i+chunk_size] for i in range(0,len(connection_ids),chunk_size)]

        for connection_list in chunked_connection_ids:
            # Send to dispatch queue
            message_attrs = {
                'AttributeName': {'StringValue': 'AttributeValue', 'DataType': 'String'}
            }
            message_body = {
                "connections": connection_list,
                "site": site,
                "status_type": status_type 
            }
            SQS.send_message(
                QueueUrl=QUEUE_URL,
                MessageBody=json.dumps(message_body),
                MessageAttributes=message_attrs,
            )

    return _get_response(200, "stream has activated this function")


#=========================================#
#======    Websocket Connections   =======#
#=========================================#

def add_connection(connection_id, site):
    """ Save the id of new connections subscribing to status at a site """
    subscriber = {
        "ConnectionID": connection_id,
        "site": site,
        "timestamp": decimal.Decimal(int(time.time())),
        "expiration": decimal.Decimal(int(time.time() + 86400)),  # connection expires in 24hrs
        "timestamp_iso": datetime.datetime.now().isoformat()
    }
    table_response = subscribers_table.put_item(Item=subscriber)
    return table_response


def remove_connection(connection_id):
    """ Remove a client from the list of subscribers, usually when the websocket closes. """
    table_response = subscribers_table.delete_item(Key={"ConnectionID": connection_id}) 
    return table_response


def get_connection_ids(site):
    """ Get a list of websocket connections subscribed to the given site """
    subscribers_query = subscribers_table.scan(
        ProjectionExpression="ConnectionID, site",
        FilterExpression=Key('site').eq(site)
    )
    site_subscribers = subscribers_query.get("Items", [])
    connection_ids = [c["ConnectionID"] for c in site_subscribers]
    return connection_ids


def send_to_connection(connection_id, data, wss_url):
    gatewayapi = boto3.client("apigatewaymanagementapi", endpoint_url=wss_url)
    dataToSend = json.dumps(data, cls=DecimalEncoder).encode('utf-8')
    post_response = gatewayapi.post_to_connection(
        ConnectionId=connection_id,
        Data=dataToSend
    )
    return post_response


#=========================================#
#=======     Status CRUD Methods    ======#
#=========================================#

def postStatus(site, statusType, status):
    ''' 
    {'statusType': 'devicesStatus', 'status': {...}}
    '''

    entry = {
        "site": site,    
        "statusType": statusType,
        "status": status,
        "server_timestamp_ms": int(time.time() * 1000),
    }
    dynamodb_entry = _empty_strings_to_dash(entry)

    # Convert floats into decimals for dynamodb
    dynamodb_entry = json.loads(json.dumps(dynamodb_entry), parse_float=decimal.Decimal)

    table_response = status_table.put_item(Item=dynamodb_entry)
    return table_response


def getStatus(site, status_type):
    table_response = status_table.get_item(Key={"site": site, "statusType": status_type})
    return table_response.get("Item", {})


#=========================================#
#=======       API Endpoints      ========#
#=========================================#

def postStatusHttp(event, context):
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
    
    response = postStatus(site, body['statusType'], body['status'])
    return _get_response(200, response)


def postStatusWs(event, context):
    '''
    Update a site's status from a websocket connection. 
    NOTE: still need to authenticate the connection as a valid site. 
    '''
    body = _get_body(event)
    try:
        site = body.get('site')
        statusType = body.get('statusType')
        status = body.get('status')
    except:
        return _get_response(400, 'Must include keys: site, statusType, status.')
    response = postStatus(site, body['statusType'], body['status'])
    return _get_response(200, response)


def getSiteDeviceStatus(event, context):
    """ Return the full status for the requested site """
    site = event['pathParameters']['site']
    status = getStatus(site, "deviceStatus")
    return _get_response(200, status)


def getAllSiteOpenStatus(event, context):
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


def updateSubscriberSite(event, context):
    '''
    Change the site associated with a connectionId. This connection will only
    be sent updates for that site. 
    '''
    connection_id = event['requestContext'].get('connectionId')
    body = _get_body(event)

    try:
        site = body.get('site')
    except:
        return _get_response(400, 'Missing the subscribers new site')

    # Update the connections table entry
    add_connection(connection_id, site)

    return _get_response(200, f"Successfully subscribed to {site}.")


def status_delivery_worker(event, context):
    """ Send site status updates to subscribing websocket clients.
    
    This function listens to the sqs queue StatusDeliveryQueue. 
    Messages in the queue contain a list of connection ids and the site and status_type used to obtain the latest 
    status to send. 
    """
    for record in event['Records']:
        logger.info(f'Message body: {record["body"]}')
        logger.info( f'Message attribute: {record["messageAttributes"]["AttributeName"]["stringValue"]}')

        # Parse the queue message content
        message = json.loads(record["body"])
        connections = message["connections"]
        site = message["site"]
        status_type = message["status_type"]

        # Get the status (to send) from dynamodb
        status = getStatus(site, status_type)

        # Send to each connected client
        for connection_id in connections:
            try: 
                send_to_connection(connection_id, status, WSS_URL)
            except Exception as e:
                print(f"Could not send to connection {connection_id}")
                print(e)
