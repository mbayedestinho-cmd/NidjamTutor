import streamlit as st
import urllib.parse

st.set_page_config(page_title="TuteurTD", page_icon="📚", layout="wide")

# ------------------------------------------------------------------
# DONNÉES DE TEST (à remplacer par Supabase plus tard)
# ------------------------------------------------------------------
DATA_INITIALE = [
    {
        "id": 1,
        "nom": "Abakar Moussa",
        "quartier": "Klemat",
        "zones_couvertes": ["Klemat", "Moursal", "Diguel"],
        "matieres": ["Mathématiques", "Physique"],
        "niveaux": ["Collège", "Lycée"],
        "experience": "+3 ans",
        "tarif_horaire": 3000,
        "telephone": "23566000001",
        "presentation": "Étudiant en 3e année de génie civil à l'université de N'Djamena. "
                         "3 ans d'expérience en soutien scolaire, spécialisé bac scientifique.",
    },
    {
        "id": 2,
        "nom": "Fatimé Hassan",
        "quartier": "Sabangali",
        "zones_couvertes": ["Sabangali", "Farcha"],
        "matieres": ["Français", "Anglais"],
        "niveaux": ["Primaire", "Collège"],
        "experience": "1-2 ans",
        "tarif_horaire": 2000,
        "telephone": "23566000002",
        "presentation": "Diplômée en lettres modernes, passionnée par la pédagogie pour "
                         "les plus jeunes. Méthode ludique et patiente.",
    },
    {
        "id": 3,
        "nom": "Ibrahim Kalzeubé",
        "quartier": "Amriguebe",
        "zones_couvertes": ["Amriguebe", "Chagoua", "Walia"],
        "matieres": ["Mathématiques", "Physique", "Chimie"],
        "niveaux": ["Lycée", "Terminale"],
        "experience": "+3 ans",
        "tarif_horaire": 3500,
        "telephone": "23566000003",
        "presentation": "Professeur vacataire au lycée, spécialiste préparation bac. "
                         "Taux de réussite élevé pour mes élèves de terminale.",
    },
    {
        "id": 4,
        "nom": "Achta Djimet",
        "quartier": "Dembé",
        "zones_couvertes": ["Dembé", "Gassi", "Ridina"],
        "matieres": ["Anglais", "Français"],
        "niveaux": ["Collège", "Lycée"],
        "experience": "Débutant",
        "tarif_horaire": 1500,
        "telephone": "23566000004",
        "presentation": "Jeune diplômée en anglais, motivée et disponible en semaine "
                         "comme le week-end.",
    },
    {
        "id": 5,
        "nom": "Mahamat Saleh",
        "quartier": "Moursal",
        "zones_couvertes": ["Moursal", "Klemat"],
        "matieres": ["Mathématiques", "Informatique"],
        "niveaux": ["Collège", "Lycée", "Terminale"],
        "experience": "1-2 ans",
        "tarif_horaire": 2500,
        "telephone": "23566000005",
        "presentation": "Étudiant en informatique, donne aussi des bases de "
                         "programmation en plus des maths classiques.",
    },
]

TOUS_NIVEAUX = ["Primaire", "Collège", "Lycée", "Terminale"]

if "repetiteurs" not in st.session_state:
    st.session_state.repetiteurs = [dict(r, statut="actif") for r in DATA_INITIALE]
    st.session_state.next_id = 6


def toutes_matieres():
    return sorted({m for r in st.session_state.repetiteurs for m in r["matieres"]})


def tous_quartiers():
    return sorted({z for r in st.session_state.repetiteurs for z in r["zones_couvertes"]})


def initiales(nom):
    parts = nom.split()
    return "".join(p[0] for p in parts[:2]).upper() if parts else "TR"


# ------------------------------------------------------------------
# STYLE (repris de la maquette TuteurTD)
# ------------------------------------------------------------------
st.markdown("""
<style>
:root {
    --bg: #0b1220;
    --surface: #121a2b;
    --surface2: #182235;
    --border: rgba(94, 234, 212, 0.18);
    --teal: #2dd4bf;
    --teal-dim: rgba(45, 212, 191, 0.12);
    --text: #e8eef7;
    --muted: #8b9bb4;
    --warning: #fbbf24;
    --radius: 16px;
    --shadow: 0 12px 40px rgba(0, 0, 0, 0.35);
}

.stApp {
    background:
        radial-gradient(ellipse at 20% 0%, rgba(45, 212, 191, 0.12), transparent 50%),
        radial-gradient(ellipse at 80% 100%, rgba(99, 102, 241, 0.1), transparent 45%),
        var(--bg);
    color: var(--text);
}
[data-testid="stHeader"] { background: transparent; }
h1, h2, h3, p, span, label, div { color: var(--text); }

/* Header */
.topbar { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
.logo {
    width: 42px; height: 42px; border-radius: 12px;
    background: linear-gradient(135deg, var(--teal), #6366f1);
    display: grid; place-items: center; font-weight: 700; font-size: 1.1rem; color: #06201c;
}
.brand h1 { font-size: 1.35rem; letter-spacing: -0.02em; margin: 0; }
.brand p { color: var(--muted); font-size: 0.82rem; margin: 0; }

/* Hero */
.hero {
    background: linear-gradient(135deg, rgba(45, 212, 191, 0.1), rgba(99, 102, 241, 0.08));
    border: 1px solid var(--border); border-radius: var(--radius);
    padding: 22px 20px; margin-bottom: 18px;
}
.hero h2 { font-size: 1.45rem; margin-bottom: 6px; }
.hero p { color: var(--muted); font-size: 0.95rem; margin: 0; }

/* Stats */
.stat {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 12px; text-align: center;
}
.stat strong { display: block; font-size: 1.25rem; color: var(--teal); }
.stat span { color: var(--muted); font-size: 0.78rem; }

/* Cards */
.card {
    background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
    padding: 16px; box-shadow: var(--shadow); margin-bottom: 14px;
}
.card-head { display: flex; gap: 12px; align-items: center; margin-bottom: 8px; }
.avatar {
    width: 48px; height: 48px; border-radius: 50%;
    background: linear-gradient(145deg, #2dd4bf, #6366f1);
    display: grid; place-items: center; font-weight: 700; color: #06201c; flex-shrink: 0;
}
.card-head h3 { font-size: 1.02rem; margin: 0; }
.card-head .meta { color: var(--muted); font-size: 0.8rem; }
.badges { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.badge {
    background: var(--teal-dim); color: var(--teal); border: 1px solid rgba(45, 212, 191, 0.25);
    font-size: 0.72rem; font-weight: 600; padding: 3px 8px; border-radius: 999px;
}
.badge.muted { background: rgba(139, 155, 180, 0.12); color: var(--muted); border-color: rgba(139, 155, 180, 0.2); }
.card p.desc { color: var(--muted); font-size: 0.86rem; }
.price { font-weight: 700; color: var(--text); font-size: 0.95rem; }
.price span { color: var(--muted); font-weight: 500; font-size: 0.78rem; }

.btn-wa {
    background: #128C7E; color: white !important; display: inline-flex; align-items: center;
    gap: 6px; padding: 9px 14px; border-radius: 10px; font-weight: 600; font-size: 0.86rem;
    text-decoration: none; margin-top: 8px;
}
.btn-wa:hover { filter: brightness(1.1); }

.empty {
    text-align: center; padding: 36px 16px; color: var(--muted);
    border: 1px dashed var(--border); border-radius: var(--radius);
}
.status { display: inline-block; padding: 3px 8px; border-radius: 999px; font-size: 0.72rem; font-weight: 700; }
.status.actif { background: rgba(45,212,191,0.15); color: var(--teal); }
.status.attente { background: rgba(251,191,36,0.15); color: var(--warning); }

/* Streamlit widgets */
[data-testid="stTextInput"] input, [data-testid="stNumberInput"] input,
[data-baseweb="select"] > div, textarea {
    background: var(--surface) !important; border: 1px solid var(--border) !important; color: var(--text) !important;
    border-radius: 10px !important;
}
button[kind="primary"] {
    background: linear-gradient(90deg, var(--teal), #34d399) !important; color: #06201c !important; border: none !important;
}
.stTabs [data-baseweb="tab"] { color: var(--muted); }
.stTabs [aria-selected="true"] { color: var(--teal) !important; }
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------
# HEADER
# ------------------------------------------------------------------
st.markdown("""
<div class="topbar">
  <div class="logo">T</div>
  <div class="brand">
    <h1>TuteurTD</h1>
    <p>Répétiteurs de maison à N'Djamena</p>
  </div>
</div>
""", unsafe_allow_html=True)

tab_parent, tab_tuteur, tab_admin = st.tabs(["👨‍👩‍👧 Parent", "📚 Répétiteur", "🛠️ Admin"])

# ------------------------------------------------------------------
# ONGLET PARENT
# ------------------------------------------------------------------
with tab_parent:
    actifs = [r for r in st.session_state.repetiteurs if r["statut"] == "actif"]

    st.markdown(f"""
    <div class="hero">
      <h2>Trouvez le bon répétiteur</h2>
      <p>Filtrez par matière, niveau, quartier et budget. Contactez directement sur WhatsApp.</p>
    </div>
    """, unsafe_allow_html=True)

    s1, s2, s3 = st.columns(3)
    with s1:
        st.markdown(f'<div class="stat"><strong>{len(actifs)}</strong><span>profils visibles</span></div>', unsafe_allow_html=True)
    with s2:
        st.markdown(f'<div class="stat"><strong>{len(tous_quartiers())}</strong><span>quartiers couverts</span></div>', unsafe_allow_html=True)
    with s3:
        st.markdown(f'<div class="stat"><strong>{len(toutes_matieres())}</strong><span>matières</span></div>', unsafe_allow_html=True)

    st.write("")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        matiere_filtre = st.selectbox("Matière", ["Toutes"] + toutes_matieres())
    with c2:
        niveau_filtre = st.selectbox("Niveau", ["Tous"] + TOUS_NIVEAUX)
    with c3:
        quartier_filtre = st.selectbox("Quartier / zone", ["Tous"] + tous_quartiers())
    with c4:
        budget_max = st.number_input("Budget max (FCFA/h)", min_value=0, value=5000, step=250)

    def correspond(r):
        if r["statut"] != "actif":
            return False
        if matiere_filtre != "Toutes" and matiere_filtre not in r["matieres"]:
            return False
        if niveau_filtre != "Tous" and niveau_filtre not in r["niveaux"]:
            return False
        if quartier_filtre != "Tous" and quartier_filtre not in r["zones_couvertes"]:
            return False
        if r["tarif_horaire"] > budget_max:
            return False
        return True

    resultats = [r for r in st.session_state.repetiteurs if correspond(r)]

    st.write("")
    if not resultats:
        st.markdown('<div class="empty">Aucun profil ne correspond à vos filtres.</div>', unsafe_allow_html=True)
    else:
        cols = st.columns(3)
        for i, r in enumerate(resultats):
            with cols[i % 3]:
                badges = "".join(f'<span class="badge">{m}</span>' for m in r["matieres"])
                badges += "".join(f'<span class="badge muted">{n}</span>' for n in r["niveaux"])
                message = urllib.parse.quote(
                    f"Bonjour {r['nom']}, je vous contacte via TuteurTD pour des cours particuliers."
                )
                lien_whatsapp = f"https://wa.me/{r['telephone']}?text={message}"
                st.markdown(f"""
                <div class="card">
                  <div class="card-head">
                    <div class="avatar">{initiales(r['nom'])}</div>
                    <div>
                      <h3>{r['nom']}</h3>
                      <div class="meta">{r['quartier']} · {r['experience']}</div>
                    </div>
                  </div>
                  <div class="badges">{badges}</div>
                  <p class="desc">{r['presentation']}</p>
                  <div class="price">{r['tarif_horaire']:,} <span>FCFA/h</span></div>
                  <a class="btn-wa" href="{lien_whatsapp}" target="_blank" rel="noopener">💬 Contacter sur WhatsApp</a>
                </div>
                """.replace(",", " "), unsafe_allow_html=True)

# ------------------------------------------------------------------
# ONGLET RÉPÉTITEUR (inscription)
# ------------------------------------------------------------------
with tab_tuteur:
    st.markdown("""
    <div class="hero">
      <h2>Devenir répétiteur</h2>
      <p>Créez votre profil en quelques minutes. Les parents pourront vous trouver et vous contacter.</p>
    </div>
    """, unsafe_allow_html=True)

    if st.session_state.get("profil_ajoute"):
        st.success("✅ Profil enregistré (démo). En production, il passerait en validation admin puis deviendrait visible.")
        st.session_state.profil_ajoute = False

    with st.form("form_tuteur", clear_on_submit=True):
        fc1, fc2 = st.columns(2)
        with fc1:
            nom = st.text_input("Nom complet *", placeholder="Ex: Amina Mahamat")
            quartier = st.text_input("Quartier principal *", placeholder="Ex: Chagoua")
            matiere = st.text_input("Matière principale *", placeholder="Ex: Mathématiques")
            niveau = st.selectbox("Niveau visé *", [""] + TOUS_NIVEAUX + ["Université"])
        with fc2:
            telephone = st.text_input("Téléphone WhatsApp *", placeholder="Ex: 23566001234")
            tarif = st.number_input("Tarif indicatif (FCFA/heure) *", min_value=500, step=250, value=2000)
            experience = st.selectbox("Expérience", ["Débutant", "1-2 ans", "+3 ans"])
            dispo = st.text_input("Disponibilités", placeholder="Ex: Soirs + week-end")
        bio = st.text_area("Présentation courte", placeholder="Parlez de votre parcours, méthode, résultats…")

        submitted = st.form_submit_button("Publier mon profil")
        if submitted:
            if not nom or not telephone or not quartier or not matiere or not niveau:
                st.error("Merci de remplir tous les champs obligatoires (*).")
            else:
                st.session_state.repetiteurs.insert(0, {
                    "id": st.session_state.next_id,
                    "nom": nom.strip(),
                    "quartier": quartier.strip(),
                    "zones_couvertes": [quartier.strip()],
                    "matieres": [matiere.strip()],
                    "niveaux": [niveau],
                    "experience": experience,
                    "tarif_horaire": int(tarif),
                    "telephone": "".join(ch for ch in telephone if ch.isdigit()),
                    "presentation": bio.strip() or "Nouveau profil répétiteur.",
                    "statut": "attente",
                })
                st.session_state.next_id += 1
                st.session_state.profil_ajoute = True
                st.rerun()

    st.caption("* Champs obligatoires. En V1 réelle : validation admin + photo/CV optionnels.")

# ------------------------------------------------------------------
# ONGLET ADMIN
# ------------------------------------------------------------------
with tab_admin:
    st.markdown("""
    <div class="hero">
      <h2>Validation des profils</h2>
      <p>Aperçu du panneau admin : activer, suspendre, contrôler la qualité.</p>
    </div>
    """, unsafe_allow_html=True)

    hdr = st.columns([2, 2, 2, 1.5, 1.5, 1.5])
    for col, label in zip(hdr, ["Nom", "Matière", "Quartier", "Tarif", "Statut", "Action"]):
        col.markdown(f"**{label}**")
    st.markdown("<hr style='border-color: rgba(94,234,212,0.18); margin: 4px 0 8px;'>", unsafe_allow_html=True)

    for r in st.session_state.repetiteurs:
        row = st.columns([2, 2, 2, 1.5, 1.5, 1.5])
        row[0].write(r["nom"])
        row[1].write(", ".join(r["matieres"]))
        row[2].write(r["quartier"])
        row[3].write(f"{r['tarif_horaire']:,} F".replace(",", " "))
        statut_class = "actif" if r["statut"] == "actif" else "attente"
        statut_label = "Actif" if r["statut"] == "actif" else "En attente"
        row[4].markdown(f'<span class="status {statut_class}">{statut_label}</span>', unsafe_allow_html=True)
        bouton_label = "Suspendre" if r["statut"] == "actif" else "Activer"
        if row[5].button(bouton_label, key=f"toggle_{r['id']}"):
            r["statut"] = "attente" if r["statut"] == "actif" else "actif"
            st.rerun()

st.markdown(
    "<footer style='margin-top:28px;text-align:center;color:#8b9bb4;font-size:0.8rem;'>"
    "TuteurTD · Projet répétiteurs de maison · N'Djamena</footer>",
    unsafe_allow_html=True,
)
