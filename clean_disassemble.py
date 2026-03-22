import pickletools
import pickle

def clean_disassemble():
    with open("failed_payload.pkl", "rb") as f:
        try:
            for opcode, arg, pos in pickletools.genops(f):
                arg_str = repr(arg)
                if len(arg_str) > 100:
                    arg_str = arg_str[:100] + "... <truncated>"
                print(f"{pos}: {opcode.name} {arg_str}")
        except Exception as e:
            print(f"ERROR: {e}")

clean_disassemble()
