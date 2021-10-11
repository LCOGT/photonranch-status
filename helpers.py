import json, boto3, decimal


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
            if o % 1 != 0:
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
    
    

def add_item_timestamps(status_dict, timestamp):
    """ Convert all status values into dicts that include the value and a timestamp to denote age. 
    
    For example, if the original status dict is
    status = {
        "mount": {
            "mount1": {
                "declination": 89.9 
            }
        }
    },
    then running add_item_timestamps(status, 12345) will return
    status = {
        "mount": {
            "mount1": {
                "declination": {
                    "val": 89.9,
                    "timestamp": 12345
                }
            }
        }
    }
    """
    s = dict(status_dict)  # make a copy
    for device_type in s:
        if type(s[device_type]) != dict: continue
        for device_instance in s[device_type]:
            if type(s[device_type][device_instance]) != dict: continue
            for status_key in s[device_type][device_instance]:
                s[device_type][device_instance][status_key] = {
                    "val": s[device_type][device_instance][status_key],
                    "timestamp": timestamp
                }
    return s
    

def merge_dicts(main_dict, updates_dict):
    """ Recursively merges updates_dict into main_dict"""
    if not isinstance(main_dict, dict) or not isinstance(updates_dict, dict):
        return updates_dict
    for k in updates_dict:
        if k in main_dict:
            main_dict[k] = merge_dicts(main_dict[k], updates_dict[k])
        else:
            main_dict[k] = updates_dict[k]
    return main_dict
