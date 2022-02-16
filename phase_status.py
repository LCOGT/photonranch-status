
import time
from helpers import send_to_datastream
from helpers import _get_body 
from helpers import _get_response 

def phase_status_handler(event, context):
    body = _get_body(event)

    try: 
        site = body['site']
        message = body['message']
    except Exception as e:
        return _get_response(400, 'Unable to parse all required arguments. ')

    payload = {
        "timestamp": time.time(),
        "message": message,
    }
    topic = "phase_status"
    send_to_datastream(site, payload, topic)
    return _get_response(200, 'Phase status broadcasted to sites successfully.')
