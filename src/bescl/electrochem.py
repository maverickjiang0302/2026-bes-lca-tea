"""Electrochemistry of the zero-gap cell: electron bookkeeping, area resistances,
voltage budget, and the recirculation needed for mass transfer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

FARADAY = 96485.0  # C per mol e-


def K_mol_e_per_A_m2_yr(operating_h_per_yr: float) -> float:
    """Moles of electrons passed per (A m-2) per m2 per year."""
    return 3600.0 * operating_h_per_yr / FARADAY


@dataclass(frozen=True)
class AreaResistance:
    """Area-specific resistances, ohm m2."""

    anode: float
    membrane: float
    cathode: float

    @property
    def total(self) -> float:
        return self.anode + self.membrane + self.cathode


def area_resistance(cell: dict[str, Any], anode_thickness_m: float | None = None) -> AreaResistance:
    """R = t * tau / (eps * kappa) through each wastewater- or catholyte-filled layer,
    plus the membrane's own area resistance."""
    g, e = cell["geometry"], cell["electrolyte"]
    t_an = g["anode_thickness_m"] if anode_thickness_m is None else anode_thickness_m
    tau, eps = g["anode_tortuosity"], g["anode_porosity"]
    r_anode = t_an * tau / (eps * e["wastewater_conductivity_S_per_m"])
    r_cathode = g["cathode_thickness_m"] * tau / (eps * e["catholyte_conductivity_S_per_m"])
    return AreaResistance(r_anode, cell["membrane"]["area_resistance_ohm_m2"], r_cathode)


@dataclass(frozen=True)
class VoltageBudget:
    """All terms in volts. Positive V_applied means the cell consumes power."""

    E_thermo: float      # E_cathode - E_anode, thermodynamic (formal, pH 7)
    eta_ohm: float
    eta_ph: float
    eta_kin: float

    @property
    def eta_total(self) -> float:
        return self.eta_ohm + self.eta_ph + self.eta_kin

    @property
    def V_applied(self) -> float:
        return self.eta_total - self.E_thermo


def thermodynamic_cell_voltage(product: dict[str, Any], cell: dict[str, Any]) -> float:
    return product["E_cathode_V_SHE"] - cell["operation"]["anode_potential_V_SHE"]


def voltage_budget(product: dict[str, Any], cell: dict[str, Any], j_A_m2: float, *,
                   anode_thickness_m: float | None = None, ph_gradient_V: float = 0.0,
                   anode_kinetic_V: float = 0.0, cathode_kinetic_V: float = 0.0,
                   extra_overpotential_V: float = 0.0) -> VoltageBudget:
    r = area_resistance(cell, anode_thickness_m)
    return VoltageBudget(
        E_thermo=thermodynamic_cell_voltage(product, cell),
        eta_ohm=j_A_m2 * r.total,
        eta_ph=ph_gradient_V,
        eta_kin=anode_kinetic_V + cathode_kinetic_V + extra_overpotential_V,
    )


def cell_electricity_kWh_per_m2_yr(j_A_m2: float, V_applied: float, hours: float,
                                   rectifier_eff: float, inverter_eff: float) -> float:
    """Grid electricity per m2 per year. Negative = net export after DC/AC conversion."""
    if V_applied >= 0.0:
        return j_A_m2 * V_applied * hours / 1000.0 / rectifier_eff
    return j_A_m2 * V_applied * hours / 1000.0 * inverter_eff


def recirculation(cell: dict[str, Any]) -> dict[str, float]:
    """Recirculation through the spacer-filled flow channel that keeps the
    boundary layer at ~100 um. Laminar/turbulent Darcy friction with a spacer
    multiplier; returns flow, pressure drop and pump power per m2 of membrane."""
    g, op = cell["geometry"], cell["operation"]
    u = op["face_velocity_m_per_s"]
    t_ch, length = g["flow_channel_thickness_m"], g["flow_path_length_m"]
    nu, rho = op["water_kinematic_viscosity_m2_per_s"], op["water_density_kg_per_m3"]
    q_per_m2 = u * t_ch / length                 # m3 s-1 per m2 of membrane (channel width = 1/length per m2)
    d_h = 2.0 * t_ch
    re = u * d_h / nu
    f = 64.0 / re if re < 2300.0 else 0.316 * re ** -0.25
    dp = op["spacer_friction_multiplier"] * f * (length / d_h) * rho * u ** 2 / 2.0
    power = q_per_m2 * dp / op["pump_efficiency"]  # W per m2
    return {"flow_m3_per_h_per_m2": q_per_m2 * 3600.0, "reynolds": re, "pressure_drop_Pa": dp,
            "power_W_per_m2": power}
