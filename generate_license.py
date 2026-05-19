# generate_license.py
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def generate_license():
    print("=" * 50)
    print("Advanced Biometric Application - License Generator")
    print("=" * 50)

    try:
        from src.utils.license_manager import LicenseManager
    except ImportError:
        print("ERROR: Could not import LicenseManager.")
        print("Ensure src/utils/license_manager.py exists and Python path is correct.")
        sys.exit(1)  # FIX: exit with error code so scripts can detect failure

    try:
        print("\nEnter license details:")
        customer_name = input("Customer Name/Email: ").strip()
        if not customer_name:
            print("ERROR: Customer name is required.")
            sys.exit(1)

        while True:
            try:
                device_count = int(input("Number of Devices: ").strip())
                if device_count > 0:
                    break
                print("Please enter a positive number.")
            except ValueError:
                print("Please enter a valid number.")

        while True:
            try:
                days_valid = int(input("Days Valid (365 for 1 year, 30 for trial): ").strip())
                if days_valid > 0:
                    break
                print("Please enter a positive number.")
            except ValueError:
                print("Please enter a valid number.")

        manager = LicenseManager()
        license_key = manager.generate_license(customer_name, device_count, days_valid)

        print("\n" + "=" * 50)
        print("LICENSE GENERATED SUCCESSFULLY")
        print("=" * 50)
        print(f"Customer    : {customer_name}")
        print(f"Devices     : {device_count}")
        print(f"Valid for   : {days_valid} days")
        print(f"License Key : {license_key}")
        print("\nLicense file saved to: config/license.json")
        print("Share the license key with the customer for activation.")

    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(0)
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(1)


def show_license_info():
    try:
        from src.utils.license_manager import LicenseManager
    except ImportError:
        print("License manager not available.")
        sys.exit(1)

    manager = LicenseManager()
    if not manager.license_data:
        print("No license found. Run: python generate_license.py")
        return

    print("\nCURRENT LICENSE INFORMATION")
    print("=" * 40)
    info = manager.get_license_info()
    for key, value in info.items():
        if key != 'license_key':
            print(f"{key.replace('_', ' ').title():20}: {value}")
    if 'license_key' in info:
        k = info['license_key']
        print(f"{'License Key':20}: {k[:8]}...{k[-8:]}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "info":
        show_license_info()
    else:
        generate_license()
