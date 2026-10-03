import argparse

import tenuo_repair

'''Create the key files for Tenuo warrants (optional), one env file per role: root (keep it
offline), issuer, workflow worker, repair-tools worker and each approver. The workers pick them
up when they start. Every file is gitignored.
    python create_tenuo_keys.py                  # create all the key files
    python create_tenuo_keys.py --renew-issuer   # re-sign the issuer's warrant with the root key'''

parser = argparse.ArgumentParser(description="Create the key files for Tenuo warrants.")
parser.add_argument("--renew-issuer", action="store_true",
                    help="re-sign the issuer worker's warrant with the root key")
args = parser.parse_args()

if args.renew_issuer:
    tenuo_repair._renew_issuer()
else:
    tenuo_repair._keygen()
