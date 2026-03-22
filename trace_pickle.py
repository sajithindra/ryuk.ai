import pickle
import sys

def trace_unpickler(filename):
    class TracingUnpickler(pickle._Unpickler):
        pass

    original_reduce = TracingUnpickler.dispatch[pickle.REDUCE[0]]
    
    def wrapped_reduce(self):
        # Peak at the stack
        func = self.stack[-2]
        args = self.stack[-1]
        print(f"[REDUCE] Calling {func} with args {args}")
        try:
            return original_reduce(self)
        except Exception as e:
            print(f"[ERROR in REDUCE] callable: {func}, args: {args}")
            raise
            
    TracingUnpickler.dispatch[pickle.REDUCE[0]] = wrapped_reduce
    
    original_build = TracingUnpickler.dispatch[pickle.BUILD[0]]
    def wrapped_build(self):
        state = self.stack[-1]
        obj = self.stack[-2]
        print(f"[BUILD] Setting state {state} on {obj}")
        try:
            return original_build(self)
        except Exception as e:
            print(f"[ERROR in BUILD] obj: {obj}, state: {state}")
            raise

    TracingUnpickler.dispatch[pickle.BUILD[0]] = wrapped_build

    with open(filename, "rb") as f:
        # Note: _Unpickler must be used to bypass C implementation
        unpickler = TracingUnpickler(f)
        unpickler.load()

try:
    trace_unpickler("failed_payload.pkl")
except Exception as e:
    import traceback
    traceback.print_exc()

