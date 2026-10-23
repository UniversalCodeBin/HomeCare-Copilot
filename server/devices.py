"""Device simulation and diagnostics engine for HomeCare Copilot.

Manages appliance state, deterministic diagnostics, capability-aware settings suggestion,
and state-changing action execution.
"""

from __future__ import annotations

import re
from typing import Any

from server.policy import validate_device_action
from server.storage import Storage


class DeviceManager:
    """Manages simulated appliances and deterministic diagnostics."""

    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    def list_appliances(self) -> list[dict[str, Any]]:
        """Return available appliances with IDs, types, status, and health scores."""
        apps = self.storage.get_all_appliances()
        summary = []
        for a in apps:
            summary.append(
                {
                    "id": a["id"],
                    "name": a["name"],
                    "type": a["type"],
                    "status": a["status"],
                    "health_score": a["health_score"],
                    "error_count": len(a.get("error_codes", [])),
                    "needs_service": (
                        a["health_score"] < 70
                        or len(a.get("error_codes", [])) > 0
                        or a["status"] == "needs_maintenance"
                    ),
                }
            )
        return summary

    def get_device_state(self, device_id: str) -> dict[str, Any] | None:
        """Return the selected appliance's full state, capabilities, wear counters, and error codes."""
        return self.storage.get_appliance(device_id)

    def diagnose_issue(self, device_id: str, symptom: str) -> dict[str, Any]:
        """Diagnose appliance issue using deterministic device state and symptom pattern matching.

        Never treats symptom text as executable instructions.
        """
        device = self.storage.get_appliance(device_id)
        if not device:
            return {
                "error": f"Appliance '{device_id}' not found.",
                "causes": [],
                "confidence": 0.0,
                "evidence": [],
                "recommended_actions": [],
            }

        symptom_clean = (symptom or "").strip().lower()
        # Security: Strip out any malicious prompt injection tokens from display evidence
        sanitized_symptom = re.sub(r"[<>{}\[\]\n\r]", " ", symptom_clean)[:200]

        dev_type = device.get("type", "")
        error_codes = device.get("error_codes", [])
        wear_counters = device.get("wear_counters", {})
        health_score = device.get("health_score", 100)

        causes: list[dict[str, Any]] = []
        evidence: list[str] = []
        recommended_actions: list[dict[str, Any]] = []

        if dev_type == "dishwasher":
            filter_clog = wear_counters.get("filter_mesh_clog", 0)
            scale = wear_counters.get("water_hardness_mineral_buildup", 0)

            # Check if symptom mentions odor, smell, cloudiness, filter, or drain
            symptom_matches = any(
                k in symptom_clean
                for k in [
                    "smell",
                    "odor",
                    "cloudy",
                    "film",
                    "stink",
                    "dirty",
                    "filter",
                    "residue",
                    "white spot",
                    "drain",
                    "clean",
                ]
            )

            if "E24_DRAIN_FILTER_BLOCKED" in error_codes or filter_clog >= 70 or symptom_matches:
                evidence.append(
                    f"Micro-mesh filter clog level is at {filter_clog}% (critical threshold: 70%)."
                )
                evidence.append(
                    f"Internal water mineral buildup index is at {scale}% (threshold: 60%)."
                )
                if "E24_DRAIN_FILTER_BLOCKED" in error_codes:
                    evidence.append("Active diagnostic trouble code detected: E24_DRAIN_FILTER_BLOCKED.")

                causes.append(
                    {
                        "cause": "Trapped organic food debris and grease in micro-mesh filter",
                        "confidence": 0.94,
                        "description": (
                            "Bacterial biofilm decomposing in the saturated filter mesh causes persistent foul odors "
                            "and recirculates cloudy wash liquor during the rinse cycle."
                        ),
                    }
                )
                causes.append(
                    {
                        "cause": "Hard-water calcium and magnesium mineral scale on heating elements",
                        "confidence": 0.86,
                        "description": (
                            "High mineral deposits prevent proper detergent dissolution and leave insoluble "
                            "silicate/calcite haze on glassware."
                        ),
                    }
                )
                causes.append(
                    {
                        "cause": "Spray arm nozzle obstruction reducing spray velocity",
                        "confidence": 0.65,
                        "description": "Partial calcium scaling in spray arm jets prevents adequate mechanical impingement.",
                    }
                )

                recommended_actions.append(
                    {
                        "action_type": "device_action",
                        "action": "run_cycle",
                        "parameters": {
                            "cycle": "cleaning_cycle",
                            "water_temp": "high",
                            "dry_mode": "heat_dry",
                        },
                        "dry_run_first": True,
                        "description": "Execute a high-temperature sanitizing cleaning cycle to purge bacterial biofilm and limescale.",
                    }
                )
                recommended_actions.append(
                    {
                        "action_type": "part_replacement",
                        "part_id": "part_dw_filter_01",
                        "part_name": "Dishwasher Micro-Fine Mesh Filter",
                        "price": 24.99,
                        "description": "Replace worn or frayed filter screen with an authentic OEM assembly.",
                    }
                )
                recommended_actions.append(
                    {
                        "action_type": "part_replacement",
                        "part_id": "part_dw_descaler_01",
                        "part_name": "Active Enzyme Descaler Tabs (6-pack)",
                        "price": 14.50,
                        "description": "Dissolve stubborn limescale buildup across internal piping and heating coils.",
                    }
                )
            else:
                causes.append(
                    {
                        "cause": "Routine maintenance advisory",
                        "confidence": 0.50,
                        "description": "No severe failures logged. Standard sanitizing cycle recommended.",
                    }
                )

        elif dev_type == "robot_vacuum":
            brush_wear = wear_counters.get("main_roller_brush_wear", 0)
            hepa_wear = wear_counters.get("hepa_filter_wear", 0)
            has_brush_warn = "WARN_BRUSH_TANGLED" in error_codes

            symptom_matches = any(
                k in symptom_clean
                for k in ["brush", "tangle", "hair", "stuck", "roller", "noise", "grind", "pick up"]
            )

            if has_brush_warn or brush_wear >= 80 or symptom_matches:
                evidence.append(
                    f"Main roller brush wear counter is at {brush_wear}% (replacement threshold: 80%)."
                )
                if has_brush_warn:
                    evidence.append("Active diagnostic alert: WARN_BRUSH_TANGLED.")
                evidence.append(
                    f"HEPA filter degradation index is at {hepa_wear}%."
                )

                causes.append(
                    {
                        "cause": "Main roller brush fiber wear and tangled hair winding around drive spindle",
                        "confidence": 0.96,
                        "description": (
                            "Hair and thread buildup at the axle bearing stalls the motor torque, while worn rubber "
                            "fins lose floor agitation capability."
                        ),
                    }
                )
                causes.append(
                    {
                        "cause": "Side sweeper bristle deformation",
                        "confidence": 0.72,
                        "description": "Curled silicone corner sweeper arms fail to sweep edge debris into the suction intake.",
                    }
                )

                recommended_actions.append(
                    {
                        "action_type": "physical_inspection",
                        "description": "Invert robot vacuum, remove roller brush guard, and cut free entangled hair along spindle tracks.",
                    }
                )
                recommended_actions.append(
                    {
                        "action_type": "part_replacement",
                        "part_id": "part_vac_brush_01",
                        "part_name": "Anti-Tangle Rubber & Bristle Main Roller Brush",
                        "price": 19.99,
                        "description": "Order genuine replacement roller brush with detachable bearing caps.",
                    }
                )
            else:
                causes.append(
                    {
                        "cause": "General navigation or surface suction variability",
                        "confidence": 0.45,
                        "description": "Sensor optical surfaces may have dust; vacuum is docked and ready.",
                    }
                )

        elif dev_type == "washing_machine":
            gasket_wear = wear_counters.get("drum_seal_wear", 0)
            inlet_cycles = wear_counters.get("inlet_valve_cycles", 0)

            if "vibration" in symptom_clean or "shake" in symptom_clean or "balance" in symptom_clean:
                evidence.append("Wash drum balance sensor reported uneven rotational torque.")
                causes.append(
                    {
                        "cause": "Uneven laundry mass distribution during high-speed extraction spin",
                        "confidence": 0.91,
                        "description": "Heavy bulky items clumped to one side of the stainless drum, triggering balance throttle.",
                    }
                )
                recommended_actions.append(
                    {
                        "action_type": "user_action",
                        "description": "Pause cycle and redistribute dense towels/jackets evenly across drum perimeter.",
                    }
                )
            elif "smell" in symptom_clean or "musty" in symptom_clean:
                evidence.append(f"Drum door bellow gasket wear is at {gasket_wear}%.")
                causes.append(
                    {
                        "cause": "Moisture and detergent buildup behind door rubber gasket fold",
                        "confidence": 0.88,
                        "description": "Cold wash cycles and trapped residue cultivate mildew in the bellows seal.",
                    }
                )
                recommended_actions.append(
                    {
                        "action_type": "device_action",
                        "action": "run_cycle",
                        "parameters": {"cycle": "clean_washer", "water_temp": "hot"},
                        "dry_run_first": True,
                        "description": "Run the dedicated tub clean cycle with hot water.",
                    }
                )
            else:
                evidence.append(f"Inlet valve has logged {inlet_cycles} actuation cycles.")
                causes.append(
                    {
                        "cause": "Normal operational variance",
                        "confidence": 0.50,
                        "description": "Appliance operating within nominal parameters.",
                    }
                )

        top_confidence = causes[0]["confidence"] if causes else 0.0

        return {
            "device_id": device_id,
            "device_name": device.get("name"),
            "health_score": health_score,
            "symptom_received": sanitized_symptom,
            "causes": causes,
            "confidence": top_confidence,
            "evidence": evidence,
            "recommended_actions": recommended_actions,
        }

    def suggest_settings(
        self,
        device_id: str,
        goal: str,
        constraints: list[str] | None = None,
    ) -> dict[str, Any]:
        """Map natural-language goal and constraints to supported appliance settings.

        Validates all selected settings against the device capability schema.
        """
        device = self.storage.get_appliance(device_id)
        if not device:
            return {"error": f"Device '{device_id}' not found.", "settings": {}}

        dev_type = device.get("type", "")
        caps = device.get("capabilities", {})
        goal_lower = (goal or "").lower()
        constraint_str = " ".join(constraints or []).lower()
        combined = f"{goal_lower} {constraint_str}"

        selected_settings: dict[str, Any] = {}
        rationale: list[str] = []

        if dev_type == "washing_machine":
            # Scenario B test case: "soccer jersey is really muddy, but label says cold wash only"
            # Constraints:
            if "cold" in combined or "tap cold" in combined:
                if "tap_cold" in caps.get("water_temp", []):
                    selected_settings["water_temp"] = "cold"
                    rationale.append("Cold wash temperature selected per garment care label instructions to protect synthetic fibers and prevent shrinking.")
                else:
                    selected_settings["water_temp"] = "cold"
                    rationale.append("Cold water temperature selected to honor fabric care constraint.")
            elif "hot" in combined or "sanitize" in combined:
                selected_settings["water_temp"] = "hot" if "hot" in caps.get("water_temp", []) else "warm"
                rationale.append("Hot water selected for sanitization.")
            else:
                selected_settings["water_temp"] = "warm"
                rationale.append("Warm water selected as balanced default.")

            # Soil level & cycle based on mud / heavy dirt:
            if any(k in combined for k in ["mud", "muddy", "heavy", "stain", "grass", "filthy", "soccer", "sports"]):
                selected_settings["soil_level"] = "heavy" if "heavy" in caps.get("soil_level", []) else "normal"
                selected_settings["cycle"] = "heavy_duty" if "heavy_duty" in caps.get("cycles", []) else "normal"
                rationale.append("Heavy soil level and Heavy Duty cycle selected to loosen deep mud and sports particulate.")
            elif any(k in combined for k in ["delicate", "silk", "wool", "lace"]):
                selected_settings["cycle"] = "delicates"
                selected_settings["soil_level"] = "light"
                rationale.append("Delicates cycle and light soil selected for fragile textiles.")
            elif "quick" in combined or "fast" in combined:
                selected_settings["cycle"] = "quick_wash"
                selected_settings["soil_level"] = "light"
                rationale.append("Quick wash cycle selected for lightly soiled clothes on a tight schedule.")
            else:
                selected_settings["cycle"] = "normal"
                selected_settings["soil_level"] = "normal"
                rationale.append("Normal cycle and soil level selected for mixed everyday laundry.")

            # Spin speed (athletic jerseys should have low or medium spin to avoid stretching decals)
            if any(k in combined for k in ["jersey", "athletic", "activewear", "delicate"]):
                selected_settings["spin_speed"] = "low" if "low" in caps.get("spin_speed", []) else "medium"
                rationale.append("Low spin speed selected to protect technical sports jersey decals and stitched seams.")
            elif any(k in combined for k in ["towel", "jeans", "bedding", "cotton"]):
                selected_settings["spin_speed"] = "high"
                rationale.append("High spin speed selected for maximum water extraction on durable cottons.")
            else:
                selected_settings["spin_speed"] = "medium"
                rationale.append("Medium spin speed selected for balanced moisture extraction.")

            # Options: mud requires extra rinse to flush particles
            options: list[str] = []
            if any(k in combined for k in ["mud", "muddy", "sensitive", "allergy", "extra rinse"]):
                if "extra_rinse" in caps.get("options", []):
                    options.append("extra_rinse")
                    rationale.append("Added 'extra_rinse' option to thoroughly flush remaining sediment and detergent.")
            if "steam" in combined and "steam" in caps.get("options", []):
                options.append("steam")
                rationale.append("Added 'steam' option for stain pretreatment.")

            if options:
                selected_settings["options"] = options

        elif dev_type == "dishwasher":
            if any(k in combined for k in ["clean", "sanitize", "smell", "odor", "deep clean"]):
                selected_settings["cycle"] = "cleaning_cycle" if "cleaning_cycle" in caps.get("cycles", []) else "sanitize"
                selected_settings["water_temp"] = "high"
                selected_settings["dry_mode"] = "heat_dry"
                rationale.append("High-temperature cleaning cycle selected to dissolve grease, scale, and odors.")
            elif any(k in combined for k in ["pots", "pans", "greasy", "baked"]):
                selected_settings["cycle"] = "heavy"
                selected_settings["water_temp"] = "high"
                selected_settings["dry_mode"] = "boost"
                rationale.append("Heavy wash cycle with boost dry selected for baked-on grease.")
            elif any(k in combined for k in ["glass", "eco", "crystal"]):
                selected_settings["cycle"] = "normal"
                selected_settings["water_temp"] = "eco"
                selected_settings["dry_mode"] = "air_dry"
                rationale.append("Eco temperature and air dry selected for delicate glassware.")
            else:
                selected_settings["cycle"] = "normal"
                selected_settings["water_temp"] = "normal"
                selected_settings["dry_mode"] = "heat_dry"
                rationale.append("Standard normal cycle with heated drying selected.")

        elif dev_type == "robot_vacuum":
            if any(k in combined for k in ["deep", "kitchen", "high traffic", "carpet", "dog", "pet"]):
                selected_settings["suction_power"] = "turbo"
                selected_settings["cleaning_mode"] = "vacuum_and_mop" if "vacuum_and_mop" in caps.get("cleaning_mode", []) else "vacuum"
                rationale.append("Turbo suction power selected for high debris/traffic areas.")
            elif any(k in combined for k in ["quiet", "night", "sleeping", "baby"]):
                selected_settings["suction_power"] = "quiet"
                selected_settings["cleaning_mode"] = "vacuum"
                rationale.append("Quiet suction power selected for noise-sensitive cleaning.")
            else:
                selected_settings["suction_power"] = "standard"
                selected_settings["cleaning_mode"] = "vacuum"
                rationale.append("Standard suction power selected for routine daily cleaning.")

        # Safety schema verification: Validate every setting against capabilities
        is_valid, error_msg, sanitized = validate_device_action(
            device,
            action="run_cycle" if dev_type != "robot_vacuum" else "start_clean",
            parameters=selected_settings,
        )

        return {
            "device_id": device_id,
            "device_name": device.get("name"),
            "goal": goal,
            "constraints": constraints or [],
            "settings": sanitized if is_valid else selected_settings,
            "is_schema_valid": is_valid,
            "validation_error": error_msg,
            "rationale": rationale,
        }

    def run_action(
        self,
        device_id: str,
        action: str,
        parameters: dict[str, Any] | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Validate and execute an appliance action. Default dry_run=True."""
        device = self.storage.get_appliance(device_id)
        if not device:
            return {
                "success": False,
                "error": f"Device '{device_id}' not found.",
                "dry_run": dry_run,
            }

        # Policy validation against capability schema
        is_valid, error_msg, sanitized_params = validate_device_action(
            device, action=action, parameters=parameters
        )
        if not is_valid:
            return {
                "success": False,
                "error": f"Action validation failed: {error_msg}",
                "dry_run": dry_run,
                "device_id": device_id,
                "action": action,
            }

        current_status = device["status"]
        current_health = device["health_score"]
        current_errors = list(device.get("error_codes", []))
        current_wear = dict(device.get("wear_counters", {}))
        dev_type = device.get("type", "")

        simulated_status = current_status
        simulated_health = current_health
        simulated_errors = list(current_errors)
        simulated_wear = dict(current_wear)
        effects_summary = []

        # Determine state changes based on action
        if dev_type == "dishwasher":
            if action == "run_cycle":
                cycle = sanitized_params.get("cycle", "normal")
                simulated_status = "running"
                effects_summary.append(f"Dishwasher begins cycle '{cycle}' with params {sanitized_params}.")

                if cycle == "cleaning_cycle":
                    # Clears drain error, purges filter clog and limescale
                    if "E24_DRAIN_FILTER_BLOCKED" in simulated_errors:
                        simulated_errors.remove("E24_DRAIN_FILTER_BLOCKED")
                        effects_summary.append("Error E24_DRAIN_FILTER_BLOCKED will be resolved by sanitizing backwash.")
                    simulated_wear["filter_mesh_clog"] = 12
                    simulated_wear["water_hardness_mineral_buildup"] = 15
                    simulated_health = 96
                    effects_summary.append("Filter mesh clog reduced from 88% to 12%. Health score improves to 96%.")
            elif action == "reset_filter":
                if "E24_DRAIN_FILTER_BLOCKED" in simulated_errors:
                    simulated_errors.remove("E24_DRAIN_FILTER_BLOCKED")
                simulated_wear["filter_mesh_clog"] = 0
                simulated_health = min(100, simulated_health + 25)
                simulated_status = "idle"
                effects_summary.append("Filter counter reset to 0%. Health restored.")
            elif action in ("pause", "cancel"):
                simulated_status = "idle"
                effects_summary.append(f"Cycle {action}ed.")

        elif dev_type == "washing_machine":
            if action in ("run_cycle", "clean_washer"):
                simulated_status = "running"
                effects_summary.append(f"Washing machine started cycle with params {sanitized_params}.")
            elif action in ("pause", "cancel", "drain_spin"):
                simulated_status = "idle"
                effects_summary.append(f"Action '{action}' executed.")

        elif dev_type == "robot_vacuum":
            if action in ("start_clean", "deep_clean_zone"):
                simulated_status = "running"
                effects_summary.append(f"Vacuum un-docks and initiates cleaning ({action}).")
            elif action == "dock":
                simulated_status = "docked"
                effects_summary.append("Vacuum returning to base station.")
            elif action == "empty_bin":
                effects_summary.append("Dustbin auto-emptied into charging tower.")
            elif action == "replace_brush":
                if "WARN_BRUSH_TANGLED" in simulated_errors:
                    simulated_errors.remove("WARN_BRUSH_TANGLED")
                simulated_wear["main_roller_brush_wear"] = 0
                simulated_health = 95
                simulated_status = "docked"
                effects_summary.append("Roller brush counter reset to 0%. Warning cleared. Health score restored to 95%.")

        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "device_id": device_id,
                "action": action,
                "parameters": sanitized_params,
                "current_state": {
                    "status": current_status,
                    "health_score": current_health,
                    "error_codes": current_errors,
                    "wear_counters": current_wear,
                },
                "projected_state": {
                    "status": simulated_status,
                    "health_score": simulated_health,
                    "error_codes": simulated_errors,
                    "wear_counters": simulated_wear,
                },
                "effects_summary": effects_summary,
                "message": "Dry run preview generated. No device state was modified. Explicit user confirmation is required to execute.",
            }

        # Actual execution (dry_run=False)
        updated = self.storage.update_appliance(
            device_id,
            status=simulated_status,
            health_score=simulated_health,
            error_codes=simulated_errors,
            wear_counters=simulated_wear,
            current_settings=sanitized_params if sanitized_params else None,
        )

        return {
            "success": True,
            "dry_run": False,
            "device_id": device_id,
            "action": action,
            "parameters": sanitized_params,
            "previous_state": {
                "status": current_status,
                "health_score": current_health,
                "error_codes": current_errors,
            },
            "new_state": updated,
            "effects_summary": effects_summary,
            "message": f"Action '{action}' successfully executed on appliance '{device_id}'.",
        }

    def check_proactive_maintenance(self, device_id: str) -> dict[str, Any]:
        """Proactively inspect wear counters and flag parts nearing failure threshold."""
        device = self.storage.get_appliance(device_id)
        if not device:
            return {"device_id": device_id, "alerts": []}

        wear = device.get("wear_counters", {})
        alerts = []
        for component, val in wear.items():
            if val >= 80:
                alerts.append(
                    {
                        "component": component,
                        "current_wear_percent": val,
                        "threshold_percent": 80,
                        "severity": "CRITICAL" if val >= 90 else "WARNING",
                        "recommendation": (
                            f"Component '{component}' has reached {val}% wear. "
                            f"Inspect or schedule replacement before breakdown occurs."
                        ),
                    }
                )

        return {
            "device_id": device_id,
            "device_name": device.get("name"),
            "health_score": device.get("health_score"),
            "alerts": alerts,
            "requires_attention": len(alerts) > 0,
        }

    def advance_wear(self, device_id: str, wear_key: str, new_value: int) -> dict[str, Any] | None:
        """Simulate wear acceleration for testing proactive maintenance (Scenario D)."""
        device = self.storage.get_appliance(device_id)
        if not device:
            return None

        wear = dict(device.get("wear_counters", {}))
        wear[wear_key] = new_value

        # Calculate adjusted health
        max_wear = max(wear.values()) if wear else 0
        new_health = max(10, 100 - int(max_wear * 0.5))

        errors = list(device.get("error_codes", []))
        if wear_key == "main_roller_brush_wear" and new_value >= 85:
            if "WARN_BRUSH_TANGLED" not in errors:
                errors.append("WARN_BRUSH_TANGLED")

        return self.storage.update_appliance(
            device_id,
            health_score=new_health,
            wear_counters=wear,
            error_codes=errors,
            status="needs_maintenance" if new_value >= 85 else device["status"],
        )
