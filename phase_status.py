import time, os, boto3, json, decimal
from boto3.dynamodb.conditions import  Key
from helpers import send_to_datastream
from helpers import _get_body 
from helpers import _get_response 
from helpers import DecimalEncoder

try:
    dynamodb = boto3.resource('dynamodb')
    phase_status_table = dynamodb.Table(os.getenv('PHASE_STATUS_TABLE'))
except Exception as e:
    print(e)

# Use local dynamodb if running with serverless-offline
if os.getenv('IS_OFFLINE'):
    print(os.getenv('IS_OFFLINE'))
    resource = boto3.resource('dynamodb', endpoint_url='http://localhost:9000')
    phase_status_table = resource.Table(name='photonranch-status-dev')

def post_phase_status(event, context):
    body = _get_body(event)

    try: 
        site = body['site']
        message = body['message']
    except Exception as e:
        return _get_response(400, 'Unable to parse all required arguments. ')

    timestamp = time.time()
    payload = {
        "site": site,
        "timestamp": timestamp,
        "message": message,
    }

    # Send to datastream
    topic = "phase_status"
    send_to_datastream(site, payload, topic)

    # save in database
    # Convert floats into decimals for dynamodb
    payload["ttl"] = timestamp + 86400  # ttl = one day
    dynamodb_entry = json.loads(json.dumps(payload, cls=DecimalEncoder), parse_float=decimal.Decimal)
    table_response = phase_status_table.put_item(Item=dynamodb_entry)

    return _get_response(200, 'Phase status broadcasted to sites successfully.')


def get_phase_status(event, context):
    try: 
        site = event['pathParameters']['site']
    except Exception as e:
        return _get_response(400, 'Missing path parameter site')

    max_age_seconds = event.get('queryStringParameters', {}).get('max_age_seconds', 3600)  # default max age is 1 hour

    timestamp_cutoff = int(time.time() - int(max_age_seconds))
    phase_status = phase_status_table.query(
        Limit=3,
        ScanIndexForward=False,  # sort by most recent first
        KeyConditionExpression=Key('site').eq(site) & Key('timestamp').gt(timestamp_cutoff)
    )
    return _get_response(200, phase_status['Items'])
    

if __name__=="__main__":

    phase_status_table = dynamodb.Table('phase-status-dev')
    payload = json.dumps({
        "site": "tst",
        "message": "a phase message 2",
    })
    #post_phase_status({"body": payload}, {})
    event = {
        "pathParameters": {
            "site": "tst"
        }, 
        "queryStringParameters": {
            "max_age_seconds": "3600"
        }
    }
    context = {}
    ps = get_phase_status(event, context)
    print(ps['body'])
