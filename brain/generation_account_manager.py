from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.generation_provider import GenerationAccount, AccountHealthStatus, GenerationFailureClass


class GenerationAccountManager:
    """Multi-account manager for balancing generation workloads and tracking credits."""

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self.state_path = config_path.parent / "account_states.json"
        self._lock = threading.RLock()
        self.accounts: Dict[str, GenerationAccount] = {}
        
        self._load_accounts()

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _load_accounts(self) -> None:
        with self._lock:
            accounts_list = self._load_accounts_from_config()
            for acc in accounts_list:
                self.accounts[acc.account_id] = acc
            self._load_state()

    def _load_accounts_from_config(self) -> List[GenerationAccount]:
        """Parse mission_control.json power_accounts and daily_accounts."""
        if not self.config_path.exists():
            return []
            
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)
        except Exception:
            return []
            
        accounts_found = []
        
        # Check both root level and under google_flow_accounts
        flow_data = config_data.get("google_flow_accounts", {})
        power_list = flow_data.get("power_accounts") or config_data.get("power_accounts", [])
        daily_list = flow_data.get("daily_accounts") or config_data.get("daily_accounts", [])

        def _parse_list(acc_list: List[Dict[str, Any]], default_priority: int) -> None:
            for item in acc_list:
                profile_num = item.get("profile_id") or item.get("profile", 0)
                account_id = item.get("account_id") or f"flow_profile_{profile_num}"
                if not account_id:
                    continue
                
                budget = item.get("daily_budget") or item.get("credits") or item.get("credits_daily") or 0
                
                # Check if profile is authenticated on disk
                is_auth = False
                real_email = None
                base_dir = self.config_path.parent
                prof_dir = base_dir / "browser" / f"flow_profile_{profile_num}"
                pref_file = prof_dir / "Default" / "Preferences"
                if pref_file.exists():
                    try:
                        with open(pref_file, "r", encoding="utf-8") as pf:
                            pdata = json.load(pf)
                            accs = pdata.get("account_info", [])
                            if accs and isinstance(accs, list) and len(accs) > 0:
                                real_email = accs[0].get("email")
                                is_auth = True
                    except Exception:
                        pass
                
                health = AccountHealthStatus.ACTIVE.value if is_auth else AccountHealthStatus.AUTH_REQUIRED.value

                acc = GenerationAccount(
                    account_id=account_id,
                    provider=item.get("provider", "google_flow"),
                    profile_id=profile_num,
                    display_name=item.get("display_name") or item.get("label") or account_id,
                    email=real_email or item.get("email", ""),
                    priority=item.get("priority", default_priority),
                    enabled=item.get("enabled", True),
                    daily_budget=budget,
                    remaining_budget=budget,
                    health_status=health
                )
                accounts_found.append(acc)

        _parse_list(power_list, 1)
        _parse_list(daily_list, 2)
        
        return accounts_found

    def _load_state(self) -> None:
        """Load mutable state into the accounts from account_states.json."""
        if not self.state_path.exists():
            return
            
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                state_data = json.load(f)
        except Exception:
            return
            
        for acc_id, state in state_data.items():
            if acc_id in self.accounts:
                acc = self.accounts[acc_id]
                acc.health_status = state.get("health_status", acc.health_status)
                acc.remaining_budget = state.get("remaining_budget", acc.remaining_budget)
                acc.failure_count = state.get("failure_count", acc.failure_count)
                acc.last_success = state.get("last_success")
                acc.last_failure = state.get("last_failure")
                acc.cooldown_until = state.get("cooldown_until")
                acc.total_generations = state.get("total_generations", acc.total_generations)
                acc.total_successes = state.get("total_successes", acc.total_successes)

    def save_state(self) -> None:
        """Persist account states to JSON (no credentials)."""
        with self._lock:
            state_data = {}
            for acc_id, acc in self.accounts.items():
                state_data[acc_id] = {
                    "health_status": acc.health_status,
                    "remaining_budget": acc.remaining_budget,
                    "failure_count": acc.failure_count,
                    "last_success": acc.last_success,
                    "last_failure": acc.last_failure,
                    "cooldown_until": acc.cooldown_until,
                    "total_generations": acc.total_generations,
                    "total_successes": acc.total_successes
                }
                
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(state_data, f, indent=2)

    def select_generation_account(self, provider: str = 'google_flow', exclude_ids: Optional[List[str]] = None) -> Optional[GenerationAccount]:
        """Deterministic selection considering priority, remaining budget, cooldown, health, failures."""
        with self._lock:
            candidates = []
            now_str = self._now_iso()
            exclude_ids_set = set(exclude_ids or [])
            
            for acc in self.accounts.values():
                if acc.provider != provider:
                    continue
                if acc.account_id in exclude_ids_set:
                    continue
                if not acc.enabled:
                    continue
                if acc.health_status in (
                    AccountHealthStatus.DISABLED.value,
                    AccountHealthStatus.ERROR.value,
                    AccountHealthStatus.AUTH_REQUIRED.value,
                    AccountHealthStatus.COOLDOWN.value,
                    AccountHealthStatus.EXHAUSTED.value
                ):
                    continue
                if acc.remaining_budget <= 0 and acc.daily_budget <= 0:
                    continue
                if acc.cooldown_until and acc.cooldown_until > now_str:
                    continue
                    
                candidates.append(acc)
                
            if not candidates:
                return None
                
            # Sort by: priority ASC (lower = higher priority), then remaining_budget DESC
            candidates.sort(key=lambda x: (x.priority, -x.remaining_budget))
            return candidates[0]

    def get_account(self, account_id: str) -> Optional[GenerationAccount]:
        with self._lock:
            return self.accounts.get(account_id)

    def get_all_accounts(self, provider: str = 'google_flow') -> List[GenerationAccount]:
        with self._lock:
            return [acc for acc in self.accounts.values() if acc.provider == provider]

    def report_success(self, account_id: str, credits_used: int = 0) -> None:
        with self._lock:
            acc = self.accounts.get(account_id)
            if not acc:
                return
                
            acc.last_success = self._now_iso()
            acc.failure_count = 0
            acc.total_generations += 1
            acc.total_successes += 1
            
            if acc.remaining_budget > 0 and credits_used > 0:
                acc.remaining_budget = max(0, acc.remaining_budget - credits_used)
                
            if acc.health_status in (AccountHealthStatus.ERROR.value, AccountHealthStatus.COOLDOWN.value):
                acc.health_status = AccountHealthStatus.HEALTHY.value
                acc.cooldown_until = None
                
            self.save_state()

    def report_failure(self, account_id: str, failure_class: str) -> None:
        with self._lock:
            acc = self.accounts.get(account_id)
            if not acc:
                return
                
            acc.last_failure = self._now_iso()
            acc.failure_count += 1
            acc.total_generations += 1
            
            if failure_class == GenerationFailureClass.AUTH_FAILURE.value:
                acc.health_status = AccountHealthStatus.AUTH_REQUIRED.value
            elif failure_class == GenerationFailureClass.CREDIT_EXHAUSTED.value:
                acc.health_status = AccountHealthStatus.EXHAUSTED.value
                acc.remaining_budget = 0
            elif acc.failure_count >= 3:
                acc.health_status = AccountHealthStatus.ERROR.value
                
            self.save_state()

    def set_cooldown(self, account_id: str, until: str) -> None:
        with self._lock:
            acc = self.accounts.get(account_id)
            if acc:
                acc.cooldown_until = until
                acc.health_status = AccountHealthStatus.COOLDOWN.value
                self.save_state()

    def disable_account(self, account_id: str, reason: str) -> None:
        with self._lock:
            acc = self.accounts.get(account_id)
            if acc:
                acc.enabled = False
                acc.health_status = AccountHealthStatus.DISABLED.value
                self.save_state()

    def get_account_summary(self) -> Dict[str, Any]:
        """Dashboard data summarization."""
        with self._lock:
            summary = {
                "total_accounts": len(self.accounts),
                "healthy_accounts": 0,
                "exhausted_accounts": 0,
                "error_accounts": 0,
                "disabled_accounts": 0,
                "total_remaining_budget": 0,
                "total_generations": 0,
                "providers": {}
            }
            
            for acc in self.accounts.values():
                if acc.health_status == AccountHealthStatus.HEALTHY.value:
                    summary["healthy_accounts"] += 1
                elif acc.health_status == AccountHealthStatus.EXHAUSTED.value:
                    summary["exhausted_accounts"] += 1
                elif acc.health_status == AccountHealthStatus.DISABLED.value:
                    summary["disabled_accounts"] += 1
                else:
                    summary["error_accounts"] += 1
                    
                summary["total_remaining_budget"] += acc.remaining_budget
                summary["total_generations"] += acc.total_generations
                
                if acc.provider not in summary["providers"]:
                    summary["providers"][acc.provider] = {"count": 0, "budget": 0}
                
                summary["providers"][acc.provider]["count"] += 1
                summary["providers"][acc.provider]["budget"] += acc.remaining_budget
                
            return summary
