# Lucknow 132kV Transmission Network 
# Data Sources:
#      substation  : UPPTCL Infrastructure PDF (March 2021)
#                    http://upptcl.org/upptcl-pdfs/infrastructure-1_120521.pdf
#      GPS coords  : OpenStreetMap
#      Transformer : UPPTCL published MVA Capacities 
#      Conductor   : ACSR Zebra - standard UPPTCL 132kV overhead line
#                    r=0.0632 Ω/km, x=0.3960 Ω/km  (IS-398 Part-2)
#      Line s_nom  : 100-189 MVA based on transformer bank at each end
#      peak load   : 2000 MW for Lucknow city at 132kV level (SLDC UP
#                     daily peak reports, summer 2023) 
#      Topology    : Approximate radial/ring based on geographic proximity +
#                    known UPPTCL corridor descriptions.
# NOTE: Exact line-by-line SLD is UPPTCL/PGCIL confidential.
#       Full accuracy requires RTI or official SLD access.

import pypsa
import pandas as pd
import numpy as np
import copy
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from scipy.spatial import cKDTree
import warnings
warnings.filterwarnings('ignore')

print(" LUCKNOW 132kV ")

# Step 1: Real SUBSTATION DATA
#SOURCE : UPPTCL Infrastructure LIst 

# what is Real Here : 
# -ALL names are actual UPPTCL 1232 substations in Lucknow district
# -voltage ratio : 132/33 kV  (some also 132/11 kV)
# -Transformer capacity (t_mva) : from UPPTCL published list
# -GPS coordinates : cross-checked on OSM

# what is Estimated:
# -s_nom ( line thermal limit) derived from transformer capacity
#    using standard UPPTCL practice: line limit ≈ largest transformer
# - Load allocation: proportional to transformer capacity

nodes = pd.DataFrame([
    # name                  lon        lat     t_mva  notes
    # ──────────────────────────────────────────────────────────────
    # PGCIL 400/220/132kV grid infeeds (slack buses)
    ("Neebu_Park_TRT",     80.9320,  26.8580,  189,  "3*63 MVA, 132/33kV — TRT corridor, major infeed"),
    ("Martinpurwa",        80.9650,  26.8690,  189,  "3*63 MVA, 132/33kV — northeast zone"),
    ("SGPGI",              80.9742,  26.8460,  229,  "3*63+2*20 MVA, 132/33+132/11kV — medical campus"),
    # City core substations
    ("Hanuman_Setu",       80.8890,  26.8580,  126,  "2*63 MVA, 132/33kV — river crossing"),
    ("Khurram_Nagar",      80.9170,  26.8520,  143,  "1*63+2*40 MVA, 132/33kV"),
    ("NKN",                80.9400,  26.8700,  143,  "1*63+2*40 MVA, 132/33kV — near Nishatganj"),
    ("Gomti_Nagar",        81.0020,  26.8500,  120,  "3*40 MVA, 132/33kV — IT/commercial zone"),
    ("Indira_Nagar",       80.9960,  26.8770,  80,   "2*40 MVA, 132/33kV — residential"),
    ("Chinhat",            81.0402,  26.8791,  80,   "2*40 MVA, 132/33kV — eastern industrial"),
    # Peripheral substations
    ("Sahara_City",        80.9470,  26.8205,  80,   "2*40 MVA, 132/33kV — airport/south"),
    ("Rahimabad",          80.9680,  26.7880,  80,   "2*40 MVA, 132/33kV — southern periphery"),
    ("Awas_Vikas",         80.9860,  26.8090,  80,   "2*40 MVA, 132/33kV — Sultanpur Road"),
    ("Mohaan_Road",        80.9150,  26.7970,  120,  "3*40 MVA, 132/33kV — Kanpur Road corridor"),
    ("Mohanlalganj",       80.8840,  26.7650,  40,   "1*40 MVA, 132/33kV — rural south"),
], columns=["name","lon","lat","t_mva","notes"])

#Step 2: Line topology 

#ACSR ZEBRA conductor (IS-398 Part-2) - standard for UPPTCL 132KV:
#  Resistance   r = 0.0632  Ω/km  (at 75°C)
#   Reactance    x = 0.3960  Ω/km  (at 1m GMD)
#   Charging     b = 2.74e-6 S/km
#   Thermal limit: ~240A = ~54.7 MVA at 132kV
#   But double-circuit (which UPPTCL uses on heavy corridors):
#   Effective s_nom = min(transformer MVA at both ends)

ACSR_ZEBRA_R_PER_KM = 0.0632   
ACSR_ZEBRA_X_PER_KM = 0.3960 
ACSR_ZEBRA_B_PER_KM = 2.74e-6

TOTAL_LOAD_MW       = 2000      # Lucknow 132kV summer peak (UP SLDC 2023)
POWER_FACTOR        = 0.96      # typical Indian utility load pf
PROXIMITY_DEG       = 0.11      # connection radius in degrees (~12 km)
V_VIOLATION_LIMIT   = 0.95      # pu — below this = voltage violation
THERMAL_LIMIT_PCT   = 80        # % — above this = thermal security violation

coords = nodes[["lon","lat"]].values
tree = cKDTree(coords)
#Connect substations within -12km 
pairs = tree.query_pairs(r=0.11)   #0.11 = 12km

edges = []
cap_map = dict(zip(nodes["name"], nodes["t_mva"]))
name_arr = nodes["name"].values

for i, j in pairs:
    ni, nj = nodes.iloc[i], nodes.iloc[j]
    dy = (ni["lat"] - nj["lat"]) * 111
    dx = (ni["lon"] - nj["lon"]) * 111 * np.cos(np.radians(ni["lat"]))
    km = max((dx**2 + dy**2)**0.5,1.0)
    name_i = name_arr[i]
    name_j = name_arr[j]

    #Line thermal limit = min transformer capacity at both ends
    s = min(cap_map.get(name_i, 80), cap_map.get(name_j, 80))
    edges.append({
        "bus0"       : name_i,
        "bus1"       : name_j,
        "length_km"  : round(km, 2),
        "r_ohm"      : round(ACSR_ZEBRA_R_PER_KM * km, 4),
        "x_ohm"      : round(ACSR_ZEBRA_X_PER_KM * km, 4),
        "b_siem"     : round(ACSR_ZEBRA_B_PER_KM * km, 8),
        "s_nom_mva"  : round(s, 1),
    })
edges = pd.DataFrame(edges)


#Step 3 - Build PyPSA NETWORK
n = pypsa.Network()
n.set_snapshots(["peak_load"])
 
for _, row in nodes.iterrows():
    n.add("Bus", row["name"], v_nom=132,
          x=row["lon"], y=row["lat"], carrier="AC")
 
for i, row in edges.iterrows():
    b0 = str(row["bus0"]); b1 = str(row["bus1"])
    n.add("Line", f"L{i:02d}_{b0[:7]}_{b1[:7]}",
          bus0   = b0,
          bus1   = b1,
          r      = row["r_ohm"],
          x      = row["x_ohm"],
          b      = row["b_siem"],
          s_nom  = row["s_nom_mva"],
          length = row["length_km"])
 


# - Remove Isolated Buses

connected = set(n.lines.bus0.tolist() + n.lines.bus1.tolist())
isolated = [b for b in n.buses.index if b not in connected]
for b in isolated:
    n.remove("Bus", b)
if isolated:
    print(f" Removed {len(isolated)} isolated buses: {isolated}")
else:
    print(f" NO isolated buses - all substations are connected")

#Step 4 - GENERATION & LOAD
# Real data used:
#   Total load 2000 MW - Lucknow city peak demand at 132 level
#   (UP SLDC daily reports, summer 2023; Lucknow ~13% of UP's ~15GW peak)
#
#   Load per bus proportional to transformer capacity (t_mva):
#   Larger substations serve more consumers → get more load.
#   This is standard in network planning when feeder-level data
#   is not available.
#
#   Slack bus: TRT (Neebu_Park_TRT) — largest infeed substation
#   in central Lucknow, connected to PGCIL 400/132kV at TRT.      

TOTAL_LOAD_MW  = 2000
bus_list = list(n.buses.index)
slack_bus = "Neebu_Park_TRT" if "Neebu_Park_TRT" in bus_list else bus_list[0]

n.add("Generator", "PGCIL_TRT_Infeed", bus=slack_bus,
      control="Slack", p_nom=5000,
      marginal_cost=0)

#Also add second infeed at Martinpurwa
if "Martinpurwa" in bus_list:
    n.add("Generator", "PGCL_Martinpurwa", bus="Martinpurwa",
          control="PQ", p_nom=500, p_set=200,
          q_set=60, marginal_cost=0)
    
    #Load proportional to transformer capacity
active_caps = {b: cap_map.get(b, 80) for b in bus_list if b !=slack_bus}
total_cap = sum(active_caps.values())



for b, cap in active_caps.items():
    p = round(TOTAL_LOAD_MW * cap / total_cap, 1)
    q = round(p * 0.29, 1)   # pf ≈ 0.96 → tan(φ)=0.29
    n.add("Load", f"Ld_{b}", bus=b, p_set=p, q_set=q)

#Step 5 - POWER FLOW

n.lpf()
dc_lod = (n.lines_t.p0.abs()/ n.lines.s_nom * 100).iloc[0]


try:
    n.pf(use_seed=True)
    ac_converged = True
   
except Exception as e:
    ac_converged = False
   

base_v = n.buses_t.v_mag_pu.iloc[0]
base_lod = (n.lines_t.p0.abs() / n.lines.s_nom * 100).iloc[0]
base_loss = (n.lines_t.p0 + n.lines_t.p1).abs().iloc[0].sum()


# Step 6- N-1 CONTINGENCY ANALYSIS
# Remove one line at a time, solve DC flow, record violations

results = []

for i, outage in enumerate(n.lines.index):
    n2 = copy.deepcopy(n)
    n2.remove("Line", outage)
    try:
        n2.lpf()
        v   = n2.buses_t.v_mag_pu.iloc[0]
        lod = (n2.lines_t.p0.abs() / n2.lines.s_nom * 100).iloc[0]
        results.append({
            "contingency"        : outage,
            "converged"          : True,
            "v_violations"       : int((v < V_VIOLATION_LIMIT).sum()),
            "thermal_violations" : int((lod > THERMAL_LIMIT_PCT).sum()),
            "worst_voltage_pu"   : round(v.min(), 4),
            "worst_loading_pct"  : round(lod.max(), 1),
            "worst_v_bus"        : v.idxmin(),
            "worst_load_line"    : lod.idxmax() if len(lod) > 0 else "N/A",
        })
    except Exception as e:
        results.append({"contingency": outage, "converged": False, "error": str(e)})
    if (i+1) % 5 == 0:
        print(f"  {i+1}/{len(n.lines)} done...")
 
df    = pd.DataFrame(results)
df_ok = df[df.converged == True]
df.to_csv("n1_results_real.csv", index=False)

# Step 7 : PRINT RESULTS 
print("=" * 60)
print("  LUCKNOW 132kV — RESULTS SUMMARY")
print("=" * 60)
print(f"\n  Network : {len(n.buses)} buses, {len(n.lines)} lines")
print(f"  AC flow : {'CONVERGED' if ac_converged else 'USED DC FALLBACK'}")
print(f"\n  Base Case:")
print(f"    Min voltage    : {base_v.min():.4f} pu  ({base_v.idxmin()})")
print(f"    Max voltage    : {base_v.max():.4f} pu  ({base_v.idxmax()})")
print(f"    Max loading    : {base_lod.max():.1f}%  ({base_lod.idxmax()})")
print(f"    Losses         : {base_loss:.2f} MW  ({base_loss/TOTAL_LOAD_MW*100:.2f}% of load)")
print(f"    V violations   : {(base_v < V_VIOLATION_LIMIT).sum()}")
print(f"    Thermal viol.  : {(base_lod > THERMAL_LIMIT_PCT).sum()}")
print(f"\n  N-1 Analysis ({len(df)} contingencies, {len(df_ok)} converged):")
if len(df_ok) > 0:
    wi = df_ok["worst_voltage_pu"].idxmin()
    wt = df_ok["worst_loading_pct"].idxmax()
    print(f"    Total V violations    : {df_ok['v_violations'].sum()}")
    print(f"    Total thermal viol.   : {df_ok['thermal_violations'].sum()}")
    print(f"    Worst voltage         : {df_ok.loc[wi,'worst_voltage_pu']:.4f} pu "
          f"at {df_ok.loc[wi,'worst_v_bus']}")
    print(f"    Worst loading         : {df_ok.loc[wt,'worst_loading_pct']:.1f}% "
          f"on {df_ok.loc[wt,'worst_load_line']}")
print("=" * 60)

 # Step 8 : Chart

fig = plt.figure(figsize=(20, 6))
G = gridspec.GridSpec(1, 3, figure=fig, wspace=0.40)

# Chart 1 — Voltage profile
ax1 = fig.add_subplot(G[0])
sv  = base_v.sort_values()
bar_colors = ['#E24B4A' if v < 0.95 else '#1D9E75' for v in sv]
ax1.bar(range(len(sv)), sv.values, color=bar_colors, edgecolor='white', width=0.8)
ax1.axhline(0.95, color='red', ls='--', lw=1.5, label='0.95 pu limit')
ax1.axhline(1.05, color='orange', ls='--', lw=1, label='1.05 pu limit')
ax1.set_xticks(range(len(sv)))
ax1.set_xticklabels(sv.index, rotation=90, fontsize=7)
ax1.set_title(f"Bus voltage — REAL DATA\n{len(n.buses)} UPPTCL 132kV substations", fontsize=10)
ax1.set_ylabel("Voltage (pu)"); ax1.set_ylim(0.88, 1.10)
ax1.legend(fontsize=8)
 
# Chart 2 — Line loading
ax2 = fig.add_subplot(G[1])
sl  = base_lod.sort_values(ascending=False)
bar_colors2 = ['#E24B4A' if v>100 else '#BA7517' if v>80 else '#378ADD' for v in sl]
ax2.bar(range(len(sl)), sl.values, color=bar_colors2, edgecolor='white', width=0.8)
ax2.axhline(80, color='red', ls='--', lw=1.5, label='80% security limit')
ax2.axhline(100, color='darkred', ls='-', lw=1, label='100% thermal limit')
ax2.set_xticks(range(len(sl)))
ax2.set_xticklabels(sl.index, rotation=90, fontsize=7)
ax2.set_title(f"Line loading — REAL DATA\nACSR Zebra, {len(n.lines)} lines", fontsize=10)
ax2.set_ylabel("Loading (%)"); ax2.legend(fontsize=8)
 
# Chart 3 — N-1 thermal violations
ax3 = fig.add_subplot(G[2])
top = df_ok.sort_values("thermal_violations", ascending=False).head(15)
if len(top) > 0:
    ax3.barh(range(len(top)), top.thermal_violations.values,
             color=['#E24B4A' if v>0 else '#1D9E75' for v in top.thermal_violations],
             edgecolor='white')
    ax3.set_yticks(range(len(top)))
    ax3.set_yticklabels(top.contingency, fontsize=7)
ax3.set_title("N-1 thermal violations\nTop contingencies", fontsize=10)
ax3.set_xlabel("Number of overloaded lines")
 
plt.suptitle("Lucknow 132kV Network — REAL UPPTCL DATA (ACSR Zebra, 2023 peak load)",
             fontsize=11, y=1.02)
plt.savefig("output_real.png", dpi=150, bbox_inches="tight")
plt.show()
plt.close()
 
# Geographic SLD — manual matplotlib (n.plot() has dtype bug in this PyPSA version)
fig2, ax = plt.subplots(figsize=(11, 9))
ax.set_facecolor('#f8f9fa')
fig2.patch.set_facecolor('#f8f9fa')
 
# Draw lines
for _, line in n.lines.iterrows():
    b0 = n.buses.loc[line.bus0]; b1 = n.buses.loc[line.bus1]
    loading_pct = base_lod.get(line.name, 0)
    lc = '#E24B4A' if loading_pct > 80 else '#378ADD'
    lw = 1.5 + loading_pct / 100
    ax.plot([b0.x, b1.x], [b0.y, b1.y], color=lc, lw=lw, alpha=0.7, zorder=1)
 
# Draw buses
for bname, bus in n.buses.iterrows():
    v = base_v.get(bname, 1.0)
    color = '#E24B4A' if v < 0.95 else '#1D9E75'
    sz = cap_map.get(bname, 80) / 10   # size proportional to transformer MVA
    ax.scatter(bus.x, bus.y, s=sz*15, color=color, zorder=3, edgecolors='white', lw=1.5)
    ax.annotate(bname.replace("_"," "), (bus.x, bus.y),
                xytext=(4, 4), textcoords='offset points', fontsize=7, zorder=4,
                bbox=dict(boxstyle='round,pad=0.2', fc='white', alpha=0.7, ec='none'))
 
ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
ax.set_title(f"Lucknow 132kV — REAL UPPTCL Substations\n"
             f"{len(n.buses)} substations | {len(n.lines)} lines | "
             f"ACSR Zebra | Peak load: {TOTAL_LOAD_MW} MW\n"
             f"Green = normal voltage, Red = violation | Thick/red line = heavily loaded",
             fontsize=9)
ax.grid(True, alpha=0.3, linestyle= "--")
plt.tight_layout()
plt.show()
plt.savefig("sld_real.png", dpi=150, bbox_inches="tight")
plt.close()
