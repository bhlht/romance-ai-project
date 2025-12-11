import argparse
import sys
from google.cloud import compute_v1
from google.api_core.exceptions import NotFound

# Requires: pip install google-cloud-compute

def operate_instance(project_id, zone, instance_name, operation="start"):
    """
    Starts or stops a Google Cloud Compute Engine instance.
    """
    instance_client = compute_v1.InstancesClient()
    operation_client = compute_v1.ZoneOperationsClient()

    try:
        instance = instance_client.get(project=project_id, zone=zone, instance=instance_name)
    except NotFound:
        print(f"Error: Instance {instance_name} not found in {zone}.")
        return

    if operation == "start":
        if instance.status == "RUNNING":
            print(f"Instance {instance_name} is already running.")
            return
        print(f"Starting instance {instance_name}...")
        op = instance_client.start(project=project_id, zone=zone, instance=instance_name)
    elif operation == "stop":
        if instance.status in ("TERMINATED", "STOPPED"):
            print(f"Instance {instance_name} is already stopped.")
            return
        print(f"Stopping instance {instance_name}...")
        op = instance_client.stop(project=project_id, zone=zone, instance=instance_name)
    else:
        print(f"Unknown operation: {operation}")
        return

    # Wait for operation to complete
    print(f"Waiting for operation to complete...")
    op_result = operation_client.wait_for_condition(
        project=project_id, zone=zone, operation=op.name
    )
    
    if op_result.error:
         print(f"Operation failed: {op_result.error}")
    else:
        print(f"Operation {operation} completed successfully.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manage GCP Compute Engine Instance")
    parser.add_argument("--project_id", required=True, help="GCP Project ID")
    parser.add_argument("--zone", required=True, help="GCP Zone (e.g., us-central1-a)")
    parser.add_argument("--instance_name", required=True, help="Instance Name")
    parser.add_argument("--action", choices=["start", "stop"], required=True, help="Action to perform")

    args = parser.parse_args()

    operate_instance(args.project_id, args.zone, args.instance_name, args.action)
