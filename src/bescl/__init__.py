"""bescl -- bioelectrochemical commodity limits.

A coupled techno-economic and climate-impact bound for producing commodity
chemicals and metals at the cathode of a wastewater-fed bioelectrochemical
system. Everything is normalised per m2 of membrane per year and per mole of
electrons; the plant only fixes the electron supply and the scale of downstream
equipment.

Modules
-------
config       load YAML configuration
electrochem  thermodynamics, area resistances, voltage budget, recirculation
stack        bottom-up levelised stack cost and embodied climate burden
dsp          downstream processing: gas purification, liquid concentration, metal harvest
model        assemble one product / one scenario into annual cash and carbon flows
breakeven    required values of each lever at break-even (economic and climate)
sweeps       one-at-a-time sweeps
"""

__version__ = "1.0.2"
