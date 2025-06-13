# wallet_utils.py

def get_wallet_balance(user_id: int) -> float:
    # This should later read from a Wallet table
    # For now: dummy balance
    return 500000.00

def update_wallet_balance(user_id: int, amount: float):
    # This should later update a Wallet table
    print(f"[Wallet] User {user_id} balance changed by {amount:+}")
