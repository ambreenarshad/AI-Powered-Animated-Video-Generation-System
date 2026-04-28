#agents/hitl.py
import json

def hitl_agent(state: dict) -> dict:
    """
    Human-in-the-Loop (HITL) Agent
    --------------------------------
    Role: Checkpoint control before execution continues.
    On rejection: stores feedback in state and routes back to scriptwriter.
    On approval: clears feedback and continues pipeline.
    """
    print("\n" + "="*60)
    print("       HUMAN REVIEW CHECKPOINT")
    print("="*60)
    print("\n📄 Generated Script:\n")

    try:
        print(json.dumps(state["script"], indent=2))
    except:
        print(state["script"])

    print("\n" + "="*60)
    decision = input("✅ Approve script and continue? (y/n): ").strip().lower()

    if decision != "y":
        feedback = input("📝 Feedback for regeneration: ").strip()
        print(f"\n[HITL] Script rejected. Regenerating with feedback...\n")
        state["status"] = "rejected"
        state["hitl_feedback"] = feedback
    else:
        print("[HITL] Script approved. Continuing pipeline...\n")
        state["status"] = "approved"
        state["hitl_feedback"] = ""

    return state