import os
import json
from google import genai
from google.genai import types
from dotenv import load_dotenv
from datetime import datetime
from core.watchdog_indexer import get_all_profiles, get_activity_report
from core.database import cameras_col, activity_logs_col

load_dotenv()

# Configure Gemini using new generic class pattern.
# The client gets the API key from the environment variable `GEMINI_API_KEY`.
client = genai.Client()

class RyukAgent:
    """The autonomous reasoning layer for generating tactical intelligence dossiers."""
    
    def __init__(self):
        # Using gemini-3-flash-preview as explicitly requested.
        self.model_id = "gemini-3-flash-preview"
        self.system_prompt = """
        You are 'Ryuk Intelligence', an elite asynchronous military intelligence analyst operating within an advanced surveillnace system.
        You are tasked with analyzing a target's chronological movement logs and biometric metadata.
        
        Generate a highly structured, professional Tactical Intelligence Dossier in Markdown format based strictly on the provided data.
        Your dossier MUST include:
        1.  **Subject Overview**: Brief profile summary.
        2.  **Last Known Vector**: Should specifically read as "last seen at [Location] cam" (e.g. "last seen at airport cam"). Do not over-explain this point.
        3.  **Exploratory Data Analytics**: A breakdown of the number of times each distinct location was visited within the timeframe.
        4.  **Behavioral Observations**: Key patterns detected in their movements (e.g., loitering, rapid transit, specific area focus).
        5.  **Hypothesis & Assessment**: Tactical hypotheses regarding the subject's intent based on their movement patterns, and recommendations for security personnel.
        
        Maintain absolute objectivity, a cold/professional tone, and format the output for maximum readability. Do NOT invent data outside of the provided logs.
        """
        # Create a persistent client instance for generation
        self.client = client

    def generate_dossier_stream(self, profile_meta: dict, logs: list, timeframe_label: str):
        """Synthesizes raw activity logs into a structured intelligence report asynchronously."""
        try:
            # -------------------------------------------------------------
            # As requested: "nothing from the watchdog whould go to the gemini only mongo db documentss no other data"
            # Strip PyMongo ObjectId to make it JSON serializable safely.
            # Using dict comprehension instead of deepcopy — much faster for large docs.
            # -------------------------------------------------------------
            safe_meta = {k: v for k, v in profile_meta.items() if k != '_id'}
            safe_logs = [
                {k: v for k, v in l.items() if k != '_id'}
                for l in logs
            ]
            
            # Construct the data payload using RAW MongoDB JSON exactly as stored.
            payload = f"TARGET METADATA (RAW MONGODB RECORD):\n{json.dumps(safe_meta, indent=2, default=str)}\n\n"
            payload += f"TIMEFRAME: {timeframe_label}\n\n"
            payload += f"CHRONOLOGICAL MOVEMENT LOGS (RAW MONGODB RECORDS):\n"
            
            if not safe_logs:
                payload += "[]\n"
            else:
                payload += json.dumps(safe_logs, indent=2, default=str)
            
            # Request generation
            response_stream = self.client.models.generate_content_stream(
                model=self.model_id,
                contents=payload,
                config=types.GenerateContentConfig(
                    system_instruction=self.system_prompt,
                    temperature=0.2,
                    top_p=0.95,
                    max_output_tokens=2048
                )
            )
            
            for chunk in response_stream:
                if chunk.text:
                    yield chunk.text
                    
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            yield f"\n\n### INTELLIGENCE COMPILATION ERROR\n\nThe reasoning core failed to generate the dossier due to an internal API exception. A 404 generally indicates an invalid/disabled Model ID for your region, or an incorrect Endpoint.\n\n**Error Message:**\n`{str(e)}`\n\n**Detailed Traceback:**\n```python\n{error_details}\n```"

# Singleton Instance
ryuk_agent = RyukAgent()
