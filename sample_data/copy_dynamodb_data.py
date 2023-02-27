import boto3
import json
import argparse
import os
from decimal import Decimal

def scan_table(table_name):
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(table_name)
    response = table.scan()
    items = response['Items']
    while 'LastEvaluatedKey' in response:
        response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
        items.extend(response['Items'])
    return items

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)

def save_to_json(data, path):
    with open(path, 'w') as file:
        json.dump(data, file, cls=DecimalEncoder, indent=4)

if __name__ == "__main__":
    description = """This script saves the current state of dynamodb tables to be used as 
        seed data in the local dynamodb tables used for local/offline development"""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("-s", "--stage", type=str, default="dev", help="Stage of the dynamodb table to copy, either dev or prod (default: dev)")
    args = parser.parse_args()

    status_table_name = f"photonranch-status-{args.stage}"
    phase_table_name = f"phase-status-{args.stage}"

    # Construct the paths for output files
    status_output_path = os.path.join(os.path.dirname(__file__), "statusTable.json")
    phase_output_path = os.path.join(os.path.dirname(__file__), "phaseStatusTable.json")

    # Save the status table to json
    print(f"Copying the status table {status_table_name}...")
    status_scan = scan_table(status_table_name)
    save_to_json(status_scan, status_output_path)

    # Save the phase status table to json
    print(f"Copying the phase status table {phase_table_name}...")
    phase_scan = scan_table(phase_table_name)
    save_to_json(phase_scan, phase_output_path)

    print("All copying is complete.")
