"""Compile TransFundEscrow.sol → TransFundEscrow.json (ABI + bytecode).  pip install py-solc-x"""
import json
import os

import solcx

VERSION = "0.8.24"
here = os.path.dirname(os.path.abspath(__file__))
solcx.install_solc(VERSION)
out = solcx.compile_files(
    [os.path.join(here, "TransFundEscrow.sol")],
    output_values=["abi", "bin"], solc_version=VERSION, optimize=True,
)
key = next(k for k in out if k.endswith(":TransFundEscrow"))
with open(os.path.join(here, "TransFundEscrow.json"), "w") as f:
    json.dump({"abi": out[key]["abi"], "bytecode": "0x" + out[key]["bin"]}, f, indent=1)
print("wrote TransFundEscrow.json")
