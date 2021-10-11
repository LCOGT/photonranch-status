import time
from helpers import _empty_strings_to_dash
from helpers import add_item_timestamps
from helpers import merge_dicts


def test_empty_strings_to_dash():
    test_object = {
        "emptystring": "",
        "nonemptystring": "not empty"
    }
    processed = _empty_strings_to_dash(test_object)
    assert processed['emptystring'] == '-'
    assert processed['nonemptystring'] == 'not empty'


def test_add_item_timestamps():
    timestamp = time.time()
    status_dict = {
        "mount": {
            "mount_instance_1": {
                "mount_key_1": "mount_val_1",
                "mount_key_2": 2
            }
        },
        "camera": {
            "camera_instance_1": {
                "camera_key_1": "camera_val_1",
            }
        }
    }
    status_dict_with_timestamps = add_item_timestamps(status_dict, timestamp)
    print(status_dict_with_timestamps)
    assert status_dict_with_timestamps["mount"]["mount_instance_1"]["mount_key_1"]["val"] == "mount_val_1"
    assert status_dict_with_timestamps["mount"]["mount_instance_1"]["mount_key_1"]["timestamp"] == timestamp
    assert status_dict_with_timestamps["camera"]["camera_instance_1"]["camera_key_1"]["timestamp"] == timestamp


def test_add_item_timestamps_2():
    timestamp = time.time()
    status_dict = {
        "mount": {
            "mount_instance_1": {
                "mount_key_1": "mount_val_1",
                "mount_key_2": 2
            }
        },
        "not a device type": "not a dict"
    }
    status_dict_with_timestamps = add_item_timestamps(status_dict, timestamp)
    print(status_dict_with_timestamps)
    assert status_dict_with_timestamps["mount"]["mount_instance_1"]["mount_key_1"]["val"] == "mount_val_1"
    assert status_dict_with_timestamps["mount"]["mount_instance_1"]["mount_key_1"]["timestamp"] == timestamp
    assert status_dict_with_timestamps["not a device type"] == "not a dict"

    

def test_merge_dicts():
    a = {
        "mount": {
            "mount_instance_1": {
                "mount_key_0": "replace me!",
                "mount_key_1": 1,
                "mount_key_2": 2,
                "mount_key_4": {
                    "key4.1": 41,
                    "key4.3": "replace me!" 
                }
            }
        }
    }
    b = {
        "mount": {
            "mount_instance_1": {
                "mount_key_0": 0,
                "mount_key_2": 2,
                "mount_key_3": 3,
                "mount_key_4": {
                    "key4.2": 42,
                    "key4.3": 43
                }
            }
        }
    }
    c = merge_dicts(a,b)
    assert c["mount"]["mount_instance_1"]["mount_key_0"] == 0
    assert c["mount"]["mount_instance_1"]["mount_key_1"] == 1
    assert c["mount"]["mount_instance_1"]["mount_key_2"] == 2
    assert c["mount"]["mount_instance_1"]["mount_key_3"] == 3
    assert c["mount"]["mount_instance_1"]["mount_key_4"]["key4.1"] == 41
    assert c["mount"]["mount_instance_1"]["mount_key_4"]["key4.2"] == 42
    assert c["mount"]["mount_instance_1"]["mount_key_4"]["key4.3"] == 43
