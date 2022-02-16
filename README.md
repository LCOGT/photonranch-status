# photonranch-status

This repository manages the status of observatories in the Photon Ranch network. 
This includes infrastructure for storing the data as well as the api used to send and retrieve it. 
The websockets used to update the frontend are used here but managed in a different repository, [datastreamer](https://github.com/LCOGT/datastreamer).

## Status Syntax

There are three supported values for `statusType`: 'weather', 'enclosure', and 'device'. Since different observatories 
may or may not have the same access to weather or enclosure status, they are handled separate from devices. 

The basic format of a status payload is as follows: 

```javascript
{
    "statusType": "device", // weather | enclosure | device
    "status": {
        "mount": { // type of device. camera, mount, filter_wheel, etc.
            "mount_1": {// name of specific mount instance. Usually there is just one of each device type.
                "ra": 12.345, // key/val pairs for status items.
                "dec": 67.89,
                ...
            } 
            ...
        },
        "camera": {
            "sbig_ccd_1": {
                "activity": "idle",
                "temp": -20.1, 
                ...
            }
        }
        ...
    }
}
```
## Endpoints

All of the following endpoints use the base url `https://status.photonranch.org/status`


- POST `/{site}/status`
    - Description: Send a new status
    - Authorization required: no (will be added later)
    - Path Params:
        - "site": site code that status is being sent from
    - Request body: 
        - "statusType" | string | either "weather", "enclosure", or "device"
        - "status" | json | status payload as per the example above
    - Response data: 200 if successful
    - Example request:
    ```python
    # python 3.6
    import requests, json
    url = "https://status.photonranch.org/status/tst/status"
    payload = json.dumps({
        "statusType": "weather",
        "status": {
            "observing_conditions": { # this is the type of device used for weather data
                "observing_conditions1": { # instance name of the weather device. Note: there may be more than one weather device.
                    "temperature": 15.3,
                    "wind_speed": 1.37,
                }
            }
        }
    })
    response = requests.request("POST", url, data=payload)
    print(response.json())
    ```

- POST `/phase_status`
    - Description: Send a new phase status which appears in the site status footer below the user status
    - Authorization required: no (will be added later)
    - Request body: 
        - "status" | json | status payload as per the example above
        - "site" | sitecode (eg. sro)
    - Responses: 
      - 200: successful
      - 400: missing arguments in the POST body
    - Example request:
    ```python
    # python 3.6
    import requests, json
    url = "https://status.photonranch.org/status/phase_status"
    payload = json.dumps({
        "site": "sro",
        "message": "example phase status message"
    })
    requests.request("POST", url, data=payload)
    ```
