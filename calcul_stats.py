# Calcul des stats UFC façon ufcstats.com + rangs par catégorie
# Données : https://github.com/Greco1899/scrape_ufc_stats
import re
import pandas as pd

SOURCE = "https://raw.githubusercontent.com/Greco1899/scrape_ufc_stats/main/"
ACTIVE_SINCE = pd.Timestamp.today().normalize() - pd.DateOffset(years=2)  # actif = au moins 1 combat sur 2 ans
MIN_FIGHTS = 3                               # minimum de combats UFC pour être classé

DIVS = [  # ordre important : les noms les plus longs d'abord
    "Women's Strawweight", "Women's Flyweight", "Women's Bantamweight", "Women's Featherweight",
    "Light Heavyweight", "Heavyweight", "Middleweight", "Welterweight",
    "Lightweight", "Featherweight", "Bantamweight", "Flyweight", "Strawweight",
]
ORDER = list(DIVS)


def division(w):
    w = str(w)
    for d in DIVS:
        if d in w:
            return d
    return None  # catch weight, open weight, superfight


def fight_seconds(rnd, time, fmt):
    m, s = str(time).split(":")
    last = int(m) * 60 + int(s)
    durs = re.search(r"\(([\d\-]+)\)", str(fmt))
    if not durs:  # No Time Limit
        return last
    d = [int(x) * 60 for x in durs.group(1).split("-")]
    return sum(d[: int(rnd) - 1]) + last


def of(col):
    p = col.astype(str).str.extract(r"(\d+) of (\d+)").astype(float)
    return p[0].fillna(0), p[1].fillna(0)


# --- Résultats + dates ---
r = pd.read_csv(SOURCE + "ufc_fight_results.csv")
e = pd.read_csv(SOURCE + "ufc_event_details.csv")
for df in (r, e):
    df["EVENT"] = df["EVENT"].str.strip()
r["BOUT"] = r["BOUT"].str.strip().str.replace(r"\s+", " ", regex=True)
e["DATE"] = pd.to_datetime(e["DATE"])
r = r.merge(e[["EVENT", "DATE"]], on="EVENT", how="inner")  # retire les doublons d'événements renommés
r["DIV"] = r["WEIGHTCLASS"].map(division)
r["SECS"] = [fight_seconds(a, b, c) for a, b, c in zip(r["ROUND"], r["TIME"], r["TIME FORMAT"])]

# --- Stats par combattant et par combat ---
s = pd.read_csv(SOURCE + "ufc_fight_stats.csv").dropna(subset=["FIGHTER"])
s["EVENT"] = s["EVENT"].str.strip()
s["BOUT"] = s["BOUT"].str.strip().str.replace(r"\s+", " ", regex=True)
s["FIGHTER"] = s["FIGHTER"].str.strip()
s["SIG_L"], s["SIG_A"] = of(s["SIG.STR."])
s["TD_L"], s["TD_A"] = of(s["TD"])
s["SUB"] = pd.to_numeric(s["SUB.ATT"], errors="coerce").fillna(0)
f = s.groupby(["EVENT", "BOUT", "FIGHTER"], as_index=False)[["SIG_L", "SIG_A", "TD_L", "TD_A", "SUB"]].sum()

# adversaire = l'autre combattant du même combat
opp = f.rename(columns={c: "O_" + c for c in ["FIGHTER", "SIG_L", "SIG_A", "TD_L", "TD_A", "SUB"]})
f = f.merge(opp, on=["EVENT", "BOUT"])
f = f[f["FIGHTER"] != f["O_FIGHTER"]]
f = f.merge(r[["EVENT", "BOUT", "DATE", "DIV", "SECS"]], on=["EVENT", "BOUT"], how="inner")

# homonymes : on les distingue par catégorie
tott = pd.read_csv(SOURCE + "ufc_fighter_tott.csv")
dups = set(tott.loc[tott["FIGHTER"].duplicated(), "FIGHTER"])
f["ID"] = [f"{n} ({d})" if n in dups and d else n for n, d in zip(f["FIGHTER"], f["DIV"])]

# --- Agrégation carrière (formules ufcstats.com) ---
g = f.groupby("ID").agg(
    SIG_L=("SIG_L", "sum"), SIG_A=("SIG_A", "sum"), O_SIG_L=("O_SIG_L", "sum"), O_SIG_A=("O_SIG_A", "sum"),
    TD_L=("TD_L", "sum"), TD_A=("TD_A", "sum"), O_TD_L=("O_TD_L", "sum"), O_TD_A=("O_TD_A", "sum"),
    SUB=("SUB", "sum"), SECS=("SECS", "sum"), N=("BOUT", "count"), LAST=("DATE", "max"),
)
mins = g["SECS"] / 60
out = pd.DataFrame(index=g.index)
out["SLpM"] = (g["SIG_L"] / mins).round(2)
out["Str_Acc_%"] = (100 * g["SIG_L"] / g["SIG_A"]).round(0)
out["SApM"] = (g["O_SIG_L"] / mins).round(2)
out["Str_Def_%"] = (100 * (1 - g["O_SIG_L"] / g["O_SIG_A"])).round(0)
out["TD_Avg"] = (15 * g["TD_L"] / mins).round(2)
out["TD_Acc_%"] = (100 * g["TD_L"] / g["TD_A"]).round(0)
out["TD_Def_%"] = (100 * (1 - g["O_TD_L"] / g["O_TD_A"])).round(0)
out["Sub_Avg"] = (15 * g["SUB"] / mins).round(1)
out["Combats_UFC"] = g["N"]
out["Dernier_combat"] = g["LAST"]

# catégorie = celle du dernier combat hors catch weight / open weight
cat = f.dropna(subset=["DIV"]).sort_values("DATE").groupby("ID")["DIV"].last()
out["Categorie"] = cat

out = out[(out["Dernier_combat"] >= ACTIVE_SINCE) & out["Categorie"].notna()].copy()
out["Classe"] = out["Combats_UFC"] >= MIN_FIGHTS

# --- Rangs dans la catégorie (1 = meilleur) ---
stats = {"SLpM": False, "Str_Acc_%": False, "SApM": True, "Str_Def_%": False,
         "TD_Avg": False, "TD_Acc_%": False, "TD_Def_%": False, "Sub_Avg": False}
ranked = out[out["Classe"]]
out["Effectif_categorie"] = out["Categorie"].map(ranked.groupby("Categorie").size()).where(out["Classe"])
for col, asc in stats.items():
    rk = ranked.groupby("Categorie")[col].rank(ascending=asc, method="min", na_option="keep")
    out["Rang_" + col] = rk.astype("Int64")

cols = ["Categorie", "Combats_UFC", "Dernier_combat", "Effectif_categorie"]
for c in stats:
    cols += [c, "Rang_" + c]
out = out[cols].reset_index().rename(columns={"ID": "Combattant"})
out["Effectif_categorie"] = out["Effectif_categorie"].astype("Int64")
for c in ["Str_Acc_%","Str_Def_%","TD_Acc_%","TD_Def_%"]:
    out[c] = out[c].astype("Int64")
out["Dernier_combat"] = out["Dernier_combat"].dt.strftime("%Y-%m-%d")
out["Categorie"] = pd.Categorical(out["Categorie"], ORDER, ordered=True)
out = out.sort_values(["Categorie", "Combattant"])
out = out.rename(columns={
    "Categorie": "Catégorie", "Combats_UFC": "Combats UFC", "Dernier_combat": "Dernier combat",
    "Effectif_categorie": "Classés dans la catégorie",
    "SLpM": "SLpM (coups sig. touchés/min)", "Rang_SLpM": "Rang SLpM",
    "Str_Acc_%": "Précision frappes %", "Rang_Str_Acc_%": "Rang précision frappes",
    "SApM": "SApM (coups sig. encaissés/min)", "Rang_SApM": "Rang SApM",
    "Str_Def_%": "Défense frappes %", "Rang_Str_Def_%": "Rang défense frappes",
    "TD_Avg": "Takedowns/15 min", "Rang_TD_Avg": "Rang takedowns",
    "TD_Acc_%": "Précision takedowns %", "Rang_TD_Acc_%": "Rang précision takedowns",
    "TD_Def_%": "Défense takedowns %", "Rang_TD_Def_%": "Rang défense takedowns",
    "Sub_Avg": "Soumissions/15 min", "Rang_Sub_Avg": "Rang soumissions",
})
out.to_csv("ufc_stats_par_categorie.csv", index=False)
print(len(out), "combattants")
