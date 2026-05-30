import sys
import os

# Add the parent directory to the Python path to allow relative imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from collection_analysis import generate_minimal_genre_mapping_suggestions
    print("Successfully imported generate_minimal_genre_mapping_suggestions.")

    # You can add more tests here, e.g., calling the functions with dummy data
    # For now, just successful import is the goal.

except ImportError as e:
    print(f"ImportError: {e}")
    print("Please check collection_analysis.py and its dependencies for errors.")
except Exception as e:
    print(f"An unexpected error occurred: {e}")
    import traceback
    traceback.print_exc()