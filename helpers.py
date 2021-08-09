import json, os, boto3, decimal, sys, ulid, time, random
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError


#=========================================#
#=======    Utility Functions     ========#
#=========================================#


def _get_response(status_code, body):
    if not isinstance(body, str):
        body = json.dumps(body,cls=DecimalEncoder)
    return {
        "statusCode": status_code, 
        "headers": {
            # Required for CORS support to work
            "Access-Control-Allow-Origin": "*",
            # Required for cookies, authorization headers with HTTPS
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Headers": "*",
        },
        "body": body
    }

def _get_body(event):
    try:
        return json.loads(event.get("body", ""))
    except:
        print("event body could not be JSON decoded.")
        return {}

# Helper class to convert a DynamoDB item to JSON.
class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, decimal.Decimal):
            if o % 1 > 0:
                return float(o)
            else:
                return int(o)
        return super(DecimalEncoder, self).default(o)

def _empty_strings_to_dash(d):
    for x in d:
        if d[x] == '': d[x] = '-' 
        if type(d[x]) is dict: d[x] = _empty_strings_to_dash(d[x])
    return d

def get_queue_url(queueName):
    sqs_client = boto3.client("sqs", region_name="us-east-1")
    response = sqs_client.get_queue_url(
        QueueName=queueName,
    )
    return response["QueueUrl"]

def send_to_datastream(site, data):
    sqs = boto3.client('sqs')
    queue_url = get_queue_url('datastreamIncomingQueue-dev')

    payload = {
        "topic": "sitestatus",
        "site": site,
        "data": data,
    }
    response = sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(payload, cls=DecimalEncoder),
    )
    return response
    