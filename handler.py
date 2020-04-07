import json, os, boto3, decimal, sys, ulid, logging, time
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError

from helpers import _get_response, _get_body, DecimalEncoder
from helpers import *

"""
TODO:

1. This code needs a lot of cleanup. 

    - specifically: document and adhere to data format conventions.
        eg. Inputs and Outputs for the api and ws endpoints.

    - refactor functions into logical files

2. Async send to all websocket clients. 

"""

STATUS_TABLE = os.getenv('STATUS_TABLE')
STATUS_SUBSCRIBERS = os.getenv('STATUS_CONNECTION_TABLE')
WSS_URL = os.getenv('WSS_URL')


logger = logging.getLogger("handler_logger")
logger.setLevel(logging.DEBUG)
dynamodb = boto3.resource('dynamodb')

def connection_manager(event, context):
    """
    Handles connecting and disconnecting for the Websocket
    """
    connectionID = event["requestContext"].get("connectionId")
    print(json.dumps(event.get("queryStringParameters", []), indent=2))


    if event["requestContext"]["eventType"] == "CONNECT":
        logger.info("Connect requested")

        # Check that the subscriber specified which site they are subscribed to.
        try:
            site = event["queryStringParameters"]["site"]
        except:
            return _get_response(400, "No site specified")

        # Add connectionID to the database
        table = dynamodb.Table(STATUS_SUBSCRIBERS)
        subscriber = {
            "ConnectionID": connectionID,
            "site": site,
        }
        table.put_item(Item=subscriber)
        return _get_response(200, "Connect successful.")

    elif event["requestContext"]["eventType"] in ("DISCONNECT", "CLOSE"):
        logger.info("Disconnect requested")
        
        # Remove the connectionID from the database
        table = dynamodb.Table(STATUS_SUBSCRIBERS)
        table.delete_item(Key={"ConnectionID": connectionID}) 
        return _get_response(200, "Disconnect successful.")

    else:
        logger.error("Connection manager received unrecognized eventType '{}'")
        return _get_response(500, "Unrecognized eventType.")

def _send_to_connection(connection_id, data, wss_url):
    gatewayapi = boto3.client("apigatewaymanagementapi", endpoint_url=wss_url)
    dataToSend = json.dumps(data, cls=DecimalEncoder).encode('utf-8')
    print(json.loads(dataToSend))
    try: 
        posted = gatewayapi.post_to_connection(
            ConnectionId=connection_id,
            Data=dataToSend
        )
        return posted
    except Exception as e:
        print(f"Could not send to connection {connection_id}")
        print(e)

def _send_to_subscribers(site, data):

    # Get all current connections
    table = dynamodb.Table(STATUS_SUBSCRIBERS)
    response = table.scan(
        ProjectionExpression="ConnectionID, site",
        FilterExpression=Key('site').eq(site)
    )
    items = response.get("Items", [])
    print(f"Subscribers: {items}")
    connections = [x["ConnectionID"] for x in items if "ConnectionID" in x]

    # Send the message data to all connections
    logger.debug("Broadcasting message: {}".format(data))
    #dataToSend = {"messages": [data]}
    for connectionID in connections:
        try:
            connectionResponse = _send_to_connection(connectionID, data, os.getenv('WSS_URL'))
        except:
            continue
        #print('connection response: ')
        #print(json.dumps(connectionResponse))


def streamHandler(event, context):
    table = dynamodb.Table(STATUS_TABLE)
    print(f"size of stream event: {len(event['Records'])}")
    print(json.dumps(event))
    #data = event['Records'][0]['dynamodb']['NewImage']
    records = event.get('Records', [])
    for item in records:

        pk = item['dynamodb']['Keys']['site']['S']
        sk = item['dynamodb']['Keys']['statusType']['S']
    
        print(pk)
        print(sk)
        response = table.get_item(
            Key={
                "site": pk,
                "statusType": sk
            }
        )

        # If the response object doesn't have the key 'Item', there is nothing
        # to return, so close the function.
        # Note: using context.succeed() prevents the dynamodb stream from 
        # continuously retrying a bad event (eg. an event that doesn't exist)
        if response.get('Item', 'not here') == 'not here': context.succeed()

        print(response)
        #_send_to_all_connections(data)
        #_send_to_all_connections(response.get('Item', []))
        try:
            _send_to_subscribers(pk, response.get('Item', []))
        except:
            continue

    return _get_response(200, "stream has activated this function")

#=========================================#
#=======       Core Methods       ========#
#=========================================#

def postStatus(site, statusType, status):
    ''' 
    {'statusType': 'devicesStatus', 'status': {...}}
    '''
    table = dynamodb.Table(STATUS_TABLE)

    dynamodb_entry = {
        "site": site,    
        "statusType": statusType,
        "status": status,
        "server_timestamp_ms": int(time.time() * 1000),
    }

    table_response = table.put_item(Item=dynamodb_entry)
    return table_response

def getStatus(site, statusType):
    table = dynamodb.Table(STATUS_TABLE)
    table_response = table.get_item(Key={"site": site, "statusType": statusType})
    return table_response


#=========================================#
#=======       API Endpoints      ========#
#=========================================#

def postStatusHttp(event, context):
    ''' 
    Update a site's status with a regular http request.
    Example request body: {'statusType': 'devicesStatus', 'status': {...}}
    '''
    body = _get_body(event)
    table = dynamodb.Table(STATUS_TABLE)
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
    table = dynamodb.Table(STATUS_TABLE)
    site = event['pathParameters']['site']
    table_response = getStatus(site, "deviceStatus")
    return _get_response(200, table_response)

def updateSubscriberSite(event, context):
    '''
    Change the site associated with a connectionId. This connection will only
    be sent updates for that site. 
    '''
    connectionId = event['requestContext'].get('connectionId')
    body = _get_body(event)

    try:
        site = body.get('site')
    except:
        return _get_response(400, 'Missing the subscribers new site')

    table = dynamodb.Table(STATUS_SUBSCRIBERS)
    subscriber = {
        "ConnectionID": connectionId,
        "site": site
    }
    table.put_item(Item=subscriber)
    return _get_response(200, f"Successfully subscribed to {site}.")
    



if __name__=="__main__":
    print('hello')