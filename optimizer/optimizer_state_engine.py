from __future__ import annotations
import csv
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

class TransitionError(RuntimeError):
    pass

@dataclass(frozen=True)
class TransitionRule:
    rule_id: str
    action_type: str
    target_type: str
    policy_id: str
    can_forward: bool
    can_reverse: bool

@dataclass(frozen=True)
class RefundPolicy:
    policy_id: str
    refund_class: str
    refund_rate: float | None
    one_way: bool
    behavior: str

@dataclass
class OptimizerState:
    inventory: dict[str,float] = field(default_factory=dict)
    unlocks: set[str] = field(default_factory=set)
    entity_states: dict[str,dict[str,object]] = field(default_factory=dict)
    assigned_resources: dict[str,dict[str,float]] = field(default_factory=dict)
    history: list[dict[str,object]] = field(default_factory=list)
    irreversible_markers: list[str] = field(default_factory=list)
    checkpoints: dict[str,"OptimizerState"] = field(default_factory=dict,repr=False)

    def clone(self) -> "OptimizerState":
        result=deepcopy(self)
        result.checkpoints={}
        return result

    def checkpoint(self,name:str)->None:
        self.checkpoints[name]=self.clone()

@dataclass(frozen=True)
class ActionRequest:
    action_type: str
    target_type: str
    target_id: str
    required_unlocks: tuple[str,...]=()
    costs: Mapping[str,float]=field(default_factory=dict)
    tracked_investment: Mapping[str,float]=field(default_factory=dict)
    fixed_returns: Mapping[str,float]=field(default_factory=dict)
    assigned_resources: Mapping[str,float]=field(default_factory=dict)
    state_updates: Mapping[str,object]=field(default_factory=dict)
    dependency_ids: tuple[str,...]=()
    forward_only_if_unknown: bool=False

@dataclass(frozen=True)
class Preview:
    legal: bool
    policy_id: str
    refund_class: str
    costs: dict[str,float]
    returns: dict[str,float]
    losses: dict[str,float]
    one_way: bool
    reason: str

class OptimizerTransitionEngine:
    def __init__(self,policies,rules):
        self.policies=dict(policies)
        self.rules=dict(rules)

    @classmethod
    def from_csv(cls,policy_path:str|Path,rule_path:str|Path):
        policies={}
        with Path(policy_path).open(encoding="utf-8-sig",newline="") as f:
            for r in csv.DictReader(f):
                policies[r["Policy_ID"]]=RefundPolicy(
                    r["Policy_ID"],r["Refund_Class"],
                    float(r["Refund_Rate"]) if r["Refund_Rate"] else None,
                    r["Creates_One_Way_Gate"].lower() in {"yes","assumed yes"},
                    r["Engine_Behavior"])
        rules={}
        with Path(rule_path).open(encoding="utf-8-sig",newline="") as f:
            for r in csv.DictReader(f):
                rule=TransitionRule(r["Rule_ID"],r["Action_Type"],r["Target_Type"],r["Policy_ID"],
                    r["Can_Simulate_Forward"]=="Yes",r["Can_Auto_Reverse"]=="Yes")
                rules[(rule.action_type,rule.target_type)]=rule
        return cls(policies,rules)

    def resolve_rule(self,action_type,target_type):
        return (self.rules.get((action_type,target_type))
                or self.rules.get((action_type,"*"))
                or self.rules[("unknown_action","*")])

    @staticmethod
    def _sub(inv,values):
        for k,v in values.items():
            if inv.get(k,0)<v:
                raise TransitionError(f"Insufficient {k}: need {v}, have {inv.get(k,0)}")
            inv[k]=inv.get(k,0)-float(v)

    @staticmethod
    def _add(inv,values):
        for k,v in values.items():
            inv[k]=inv.get(k,0)+float(v)

    def _refund(self,policy,req):
        inv={k:float(v) for k,v in req.tracked_investment.items()}
        if policy.refund_class=="FULL_REFUND":
            return inv,{}
        if policy.refund_class=="FULL_REFUND_CONVERTED":
            return ({k:float(v) for k,v in req.fixed_returns.items()} if req.fixed_returns else inv),{}
        if policy.refund_class=="PARTIAL_REFUND":
            if policy.refund_rate is None:
                if not req.fixed_returns:
                    raise TransitionError("Explicit fixed_returns required")
                return {k:float(v) for k,v in req.fixed_returns.items()},{}
            returns={k:v*policy.refund_rate for k,v in inv.items()}
            losses={k:v-returns[k] for k,v in inv.items()}
            return returns,losses
        if policy.refund_class=="SALVAGE_FIXED_RETURN":
            if not req.fixed_returns:
                raise TransitionError("Verified fixed_returns required")
            return {k:float(v) for k,v in req.fixed_returns.items()},inv
        if policy.refund_class=="REVERSIBLE_REALLOCATION":
            src=req.assigned_resources or req.tracked_investment
            return {k:float(v) for k,v in src.items()},{}
        if policy.refund_class in {"NOT_APPLICABLE","REVERSIBLE_STATE_CHANGE","REVERSIBLE_UNKNOWN_RETURN"}:
            return {},{}
        return {},inv

    def preview(self,state,req):
        missing=[u for u in req.required_unlocks if u not in state.unlocks]
        if missing:
            return Preview(False,"","",dict(req.costs),{},{},False,f"Missing unlocks: {missing}")
        deps=[d for d in req.dependency_ids if not state.entity_states.get(d,{}).get("available",False)]
        if deps:
            return Preview(False,"","",dict(req.costs),{},{},False,f"Missing dependencies: {deps}")
        for k,v in req.costs.items():
            if state.inventory.get(k,0)<v:
                return Preview(False,"","",dict(req.costs),{},{},False,f"Insufficient {k}")
        rule=self.resolve_rule(req.action_type,req.target_type)
        policy=self.policies[rule.policy_id]
        if policy.refund_class=="UNKNOWN_BLOCKED" and not req.forward_only_if_unknown:
            return Preview(False,policy.policy_id,policy.refund_class,dict(req.costs),{},dict(req.tracked_investment),True,"Unknown policy blocked")
        returns,losses=self._refund(policy,req)
        reason=policy.behavior
        if policy.refund_class=="REVERSIBLE_UNKNOWN_RETURN":
            reason="State-only transition; returned inventory is not credited"
        return Preview(True,policy.policy_id,policy.refund_class,dict(req.costs),returns,losses,policy.one_way,reason)

    def apply(self,state,req):
        p=self.preview(state,req)
        if not p.legal:
            raise TransitionError(p.reason)
        result=state.clone()
        self._sub(result.inventory,p.costs)
        self._add(result.inventory,p.returns)
        result.entity_states.setdefault(req.target_id,{"available":True}).update(dict(req.state_updates))
        if req.action_type=="tech_resonance_assign":
            result.assigned_resources[req.target_id]={k:float(v) for k,v in req.assigned_resources.items()}
        elif req.action_type=="tech_resonance_remove":
            result.assigned_resources.pop(req.target_id,None)
        marker=""
        if p.one_way:
            marker=f"{req.action_type}:{req.target_id}"
            result.irreversible_markers.append(marker)
        result.history.append({"action":req.action_type,"target":req.target_id,"policy":p.policy_id,
            "costs":p.costs,"returns":p.returns,"losses":p.losses,"marker":marker})
        return result

    def can_restore_checkpoint(self,current,name):
        cp=current.checkpoints.get(name)
        if cp is None:
            return False,"Checkpoint does not exist"
        if len(current.irreversible_markers)>len(cp.irreversible_markers):
            return False,f"New irreversible actions: {current.irreversible_markers[len(cp.irreversible_markers):]}"
        return True,"No new irreversible markers"

    def restore_checkpoint(self,current,name):
        ok,reason=self.can_restore_checkpoint(current,name)
        if not ok:
            raise TransitionError(reason)
        return current.checkpoints[name].clone()
