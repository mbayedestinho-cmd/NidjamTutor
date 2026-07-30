import streamlit as st
import urllib.parse

st.set_page_config(page_title="NidjamTutor", page_icon="📚", layout="wide")

# ------------------------------------------------------------------
# DONNÉES DE TEST (à remplacer par Supabase plus tard)
# ------------------------------------------------------------------
REPETITEURS = [
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

TOUTES_MATIERES = sorted({m for r in REPETITEURS for m in r["matieres"]})
TOUS_NIVEAUX = ["Primaire", "Collège", "Lycée", "Terminale"]
TOUS_QUARTIERS = sorted({z for r in REPETITEURS for z in r["zones_couvertes"]})

# ------------------------------------------------------------------
# STYLE
# ------------------------------------------------------------------
st.markdown("""
<style>
.profile-card {
    border: 1px solid #e0e0e0;
    border-radius: 10px;
    padding: 18px;
    margin-bottom: 16px;
    background-color: #fafafa;
}
.tag {
    display: inline-block;
    background-color: #eef2ff;
    color: #3730a3;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 12px;
    margin-right: 6px;
    margin-bottom: 4px;
}
.tarif {
    font-weight: 600;
    color: #15803d;
}
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------
# HEADER
# ------------------------------------------------------------------
st.title("📚 NidjamTutor")
st.caption("Trouvez un répétiteur qualifié près de chez vous, selon le niveau, la matière et le budget.")

# ------------------------------------------------------------------
# FILTRES (barre latérale)
# ------------------------------------------------------------------
with st.sidebar:
    st.header("🔍 Filtrer")
    matiere_filtre = st.selectbox("Matière", ["Toutes"] + TOUTES_MATIERES)
    niveau_filtre = st.selectbox("Niveau", ["Tous"] + TOUS_NIVEAUX)
    quartier_filtre = st.selectbox("Quartier / zone", ["Tous"] + TOUS_QUARTIERS)
    budget_max = st.slider("Budget max (FCFA / heure)", 1000, 5000, 5000, step=500)
    st.divider()
    st.caption("Vous êtes répétiteur ? L'inscription arrive bientôt sur cette app.")

# ------------------------------------------------------------------
# APPLICATION DES FILTRES
# ------------------------------------------------------------------
def correspond(r):
    if matiere_filtre != "Toutes" and matiere_filtre not in r["matieres"]:
        return False
    if niveau_filtre != "Tous" and niveau_filtre not in r["niveaux"]:
        return False
    if quartier_filtre != "Tous" and quartier_filtre not in r["zones_couvertes"]:
        return False
    if r["tarif_horaire"] > budget_max:
        return False
    return True

resultats = [r for r in REPETITEURS if correspond(r)]

# ------------------------------------------------------------------
# AFFICHAGE DES RÉSULTATS
# ------------------------------------------------------------------
st.subheader(f"{len(resultats)} répétiteur(s) trouvé(s)")

if not resultats:
    st.info("Aucun profil ne correspond à ces critères. Essayez d'élargir votre recherche.")

for r in resultats:
    with st.container():
        st.markdown('<div class="profile-card">', unsafe_allow_html=True)
        col1, col2 = st.columns([3, 1])

        with col1:
            st.markdown(f"### {r['nom']}")
            st.markdown(f"📍 {r['quartier']} — couvre : {', '.join(r['zones_couvertes'])}")
            tags = "".join(f'<span class="tag">{m}</span>' for m in r["matieres"])
            tags += "".join(f'<span class="tag">{n}</span>' for n in r["niveaux"])
            st.markdown(tags, unsafe_allow_html=True)
            st.write(r["presentation"])
            st.caption(f"Expérience : {r['experience']}")

        with col2:
            st.markdown(f"<div class='tarif'>{r['tarif_horaire']:,} FCFA/h</div>".replace(",", " "),
                         unsafe_allow_html=True)
            message = urllib.parse.quote(
                f"Bonjour {r['nom']}, je vous contacte via NidjamTutor pour des cours particuliers."
            )
            lien_whatsapp = f"https://wa.me/{r['telephone']}?text={message}"
            st.link_button("💬 Contacter sur WhatsApp", lien_whatsapp, use_container_width=True)

        st.markdown('</div>', unsafe_allow_html=True)
