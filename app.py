import streamlit as st
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
from supabase import create_client, Client

st.set_page_config(page_title="TuteurTD", page_icon="📚", layout="wide")

# ------------------------------------------------------------------
# CONNEXION SUPABASE
# ------------------------------------------------------------------
# À mettre dans .streamlit/secrets.toml (en local) ou dans les
# "Secrets" de Streamlit Community Cloud :
#
# SUPABASE_URL = "https://xxxxxxxx.supabase.co"
# SUPABASE_ANON_KEY = "eyJ...."   (clé "anon public" du projet)
#
# NOUVEAU — à configurer côté Supabase pour les fonctionnalités
# photo de profil + avis (voir migration.sql fourni à part) :
#
# 1) Storage : créer un bucket PUBLIC nommé "photos-repetiteurs"
#    + une policy INSERT pour le rôle "anon" sur ce bucket.
# 2) Table "avis" (repetiteur_id uuid, note int, commentaire text,
#    created_at timestamptz default now()) avec RLS activée :
#    - policy SELECT publique (lecture libre)
#    - policy INSERT publique (dépôt libre, modération a posteriori)
# 3) Colonne "photo_url" (text, nullable) sur la table "repetiteurs".

@st.cache_resource
def get_client() -> Client:
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_ANON_KEY"])


supabase = get_client()

TOUS_NIVEAUX = ["Primaire", "Collège", "Lycée", "Terminale"]
EXPERIENCE_POIDS = {"Débutant": 1, "1-2 ans": 2, "+3 ans": 3}
BUCKET_PHOTOS = "photos-repetiteurs"


def initiales(nom):
    parts = nom.split()
    return "".join(p[0] for p in parts[:2]).upper() if parts else "TR"


# ------------------------------------------------------------------
# ACCÈS DONNÉES
# ------------------------------------------------------------------
def charger_repetiteurs_actifs():
    """Lecture publique (clé anon) : la RLS ne renvoie que statut='actif'."""
    try:
        res = supabase.table("repetiteurs").select("*").order("created_at", desc=True).execute()
        return res.data
    except Exception as e:
        st.error("Impossible de charger les profils pour le moment. Réessayez dans un instant.")
        return []


def inserer_repetiteur(payload):
    """Insertion publique : la RLS n'autorise que statut='attente'.

    IMPORTANT : on utilise returning="minimal" car la policy SELECT
    publique n'autorise que statut='actif'. Sans ça, PostgREST tente
    de renvoyer la ligne insérée (statut='attente') après l'INSERT,
    ce qui échoue la policy SELECT et déclenche une fausse erreur RLS
    même quand l'insertion elle-même est valide.
    """
    try:
        supabase.table("repetiteurs").insert(payload, returning="minimal").execute()
        return True
    except Exception as e:
        st.error("L'enregistrement a échoué. Vérifiez vos informations et réessayez.")
        return False


def charger_repetiteurs_admin(client_admin):
    """Lecture complète (tous statuts) — nécessite un client authentifié admin."""
    try:
        res = client_admin.table("repetiteurs").select("*").order("created_at", desc=True).execute()
        return res.data
    except Exception as e:
        st.error("Impossible de charger la liste admin.")
        return []


def toggle_statut_admin(client_admin, repet_id, nouveau_statut):
    try:
        client_admin.table("repetiteurs").update({"statut": nouveau_statut}).eq("id", repet_id).execute()
        return True
    except Exception as e:
        st.error("La mise à jour a échoué (droits admin refusés ?).")
        return False


def incrementer_contact(repet_id):
    """Incrémente le compteur de clics WhatsApp via une fonction RPC
    Postgres (SECURITY DEFINER). Un update direct échouerait : anon
    n'a pas de policy UPDATE sur la table. Best-effort : un échec ici
    ne doit jamais bloquer le parent qui veut juste contacter."""
    try:
        supabase.rpc("increment_contact", {"p_id": repet_id}).execute()
    except Exception:
        pass


def uploader_photo(fichier):
    """Upload la photo vers Supabase Storage et renvoie son URL publique.
    Best-effort : si l'upload échoue, on continue sans bloquer l'inscription."""
    if fichier is None:
        return None
    try:
        ext = fichier.name.split(".")[-1].lower()
        nom_fichier = f"{uuid.uuid4()}.{ext}"
        supabase.storage.from_(BUCKET_PHOTOS).upload(
            nom_fichier,
            fichier.getvalue(),
            {"content-type": fichier.type or "image/jpeg"},
        )
        return supabase.storage.from_(BUCKET_PHOTOS).get_public_url(nom_fichier)
    except Exception:
        st.warning("La photo n'a pas pu être envoyée — le profil sera créé sans photo.")
        return None


def charger_avis_stats():
    """Retourne {repetiteur_id: (note_moyenne, nb_avis)} pour tous les profils."""
    try:
        res = supabase.table("avis").select("repetiteur_id, note").execute()
        groupes = {}
        for a in res.data:
            groupes.setdefault(a["repetiteur_id"], []).append(a["note"])
        return {rid: (sum(notes) / len(notes), len(notes)) for rid, notes in groupes.items()}
    except Exception:
        return {}


def ajouter_avis(repet_id, note, commentaire):
    """Insertion publique d'un avis.

    IMPORTANT : on utilise returning="minimal" pour la même raison que
    pour inserer_repetiteur() — sans ça, PostgREST tente de relire la
    ligne insérée après l'INSERT pour la renvoyer au client, et cette
    relecture repasse par la policy SELECT. Si cette policy SELECT
    change un jour (modération, visibilité restreinte, etc.) ou si la
    migration n'a pas encore été appliquée côté Supabase, l'insertion
    réussit mais échoue quand même à cause du RETURNING implicite.
    """
    try:
        supabase.table("avis").insert({
            "repetiteur_id": repet_id,
            "note": note,
            "commentaire": commentaire.strip() if commentaire else None,
        }, returning="minimal").execute()
        return True
    except Exception as e:
        st.error(f"L'avis n'a pas pu être enregistré. Détail technique : {e}")
        return False


def score_pertinence(r, avis_stats):
    """Combine expérience, nombre de contacts et avis pour trier par pertinence."""
    exp = EXPERIENCE_POIDS.get(r.get("experience"), 1)
    contacts = r.get("nb_contacts", 0) or 0
    moyenne, nb_avis = avis_stats.get(r["id"], (0, 0))
    return exp * 3 + contacts * 1 + moyenne * nb_avis * 2


def est_recent(created_at_str, jours=7):
    """True si le profil a été créé il y a moins de `jours` jours."""
    try:
        created = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) - created < timedelta(days=jours)
    except Exception:
        return False


# ------------------------------------------------------------------
# SESSION ADMIN (Supabase Auth)
# ------------------------------------------------------------------
def get_admin_client():
    """
    Retourne un client Supabase authentifié en tant qu'admin si une
    session valide existe dans st.session_state, sinon None.
    """
    session = st.session_state.get("admin_session")
    if not session:
        return None
    client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_ANON_KEY"])
    try:
        client.auth.set_session(session["access_token"], session["refresh_token"])
        return client
    except Exception:
        st.session_state.pop("admin_session", None)
        return None


def admin_login(email, mot_de_passe):
    try:
        client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_ANON_KEY"])
        auth_res = client.auth.sign_in_with_password({"email": email, "password": mot_de_passe})
        st.session_state.admin_session = {
            "access_token": auth_res.session.access_token,
            "refresh_token": auth_res.session.refresh_token,
        }
        return True
    except Exception:
        st.error("Identifiants incorrects.")
        return False


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
.topbar { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
.logo {
    width: 42px; height: 42px; border-radius: 12px;
    background: linear-gradient(135deg, var(--teal), #6366f1);
    display: grid; place-items: center; font-weight: 700; font-size: 1.1rem; color: #06201c;
}
.brand h1 { font-size: 1.35rem; letter-spacing: -0.02em; margin: 0; }
.brand p { color: var(--muted); font-size: 0.82rem; margin: 0; }
.hero {
    background: linear-gradient(135deg, rgba(45, 212, 191, 0.1), rgba(99, 102, 241, 0.08));
    border: 1px solid var(--border); border-radius: var(--radius);
    padding: 22px 20px; margin-bottom: 18px;
}
.hero h2 { font-size: 1.45rem; margin-bottom: 6px; }
.hero p { color: var(--muted); font-size: 0.95rem; margin: 0; }
.stat {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 12px; text-align: center;
}
.stat strong { display: block; font-size: 1.25rem; color: var(--teal); }
.stat span { color: var(--muted); font-size: 0.78rem; }
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
.avatar-img {
    width: 48px; height: 48px; border-radius: 50%; object-fit: cover; flex-shrink: 0;
    border: 1px solid var(--border);
}
.card-head h3 { font-size: 1.02rem; margin: 0; }
.card-head .meta { color: var(--muted); font-size: 0.8rem; }
.note { font-size: 0.78rem; color: var(--warning); margin-bottom: 6px; }
.note.muted { color: var(--muted); }
.badges { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.badge {
    background: var(--teal-dim); color: var(--teal); border: 1px solid rgba(45, 212, 191, 0.25);
    font-size: 0.72rem; font-weight: 600; padding: 3px 8px; border-radius: 999px;
}
.badge.muted { background: rgba(139, 155, 180, 0.12); color: var(--muted); border-color: rgba(139, 155, 180, 0.2); }
.badge.nouveau { background: rgba(251, 191, 36, 0.15); color: var(--warning); border-color: rgba(251, 191, 36, 0.3); }
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
.status {
    font-size: 0.78rem; font-weight: 600; padding: 3px 10px; border-radius: 999px;
}
.status.actif { background: rgba(45, 212, 191, 0.15); color: var(--teal); }
.status.attente { background: rgba(251, 191, 36, 0.15); color: var(--warning); }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="topbar">
  <div class="logo">T</div>
  <div class="brand">
    <h1>TuteurTD</h1>
    <p>Répétiteurs de maison à N'Djamena</p>
  </div>
</div>
""", unsafe_allow_html=True)

tab_parent, tab_tuteur, tab_admin = st.tabs(["👨‍👩‍👧 Parent", "👩‍🏫 Répétiteur", "🛠️ Admin"])

# ------------------------------------------------------------------
# ONGLET PARENT (recherche)
# ------------------------------------------------------------------
with tab_parent:
    repetiteurs = charger_repetiteurs_actifs()

    def toutes_matieres():
        return sorted({m for r in repetiteurs for m in r["matieres"]})

    def tous_quartiers():
        return sorted({z for r in repetiteurs for z in r["zones_couvertes"]})

    st.markdown("""
    <div class="hero">
      <h2>Trouvez le bon répétiteur</h2>
      <p>Filtrez par matière, niveau, quartier et budget. Contactez directement sur WhatsApp.</p>
    </div>
    """, unsafe_allow_html=True)

    s1, s2, s3 = st.columns(3)
    with s1:
        st.markdown(f'<div class="stat"><strong>{len(repetiteurs)}</strong><span>profils visibles</span></div>', unsafe_allow_html=True)
    with s2:
        st.markdown(f'<div class="stat"><strong>{len(tous_quartiers())}</strong><span>quartiers couverts</span></div>', unsafe_allow_html=True)
    with s3:
        st.markdown(f'<div class="stat"><strong>{len(toutes_matieres())}</strong><span>matières</span></div>', unsafe_allow_html=True)

    st.write("")
    search_query = st.text_input("🔍 Rechercher un nom ou un mot-clé", placeholder="Ex: Mathématiques, Amina, expérience...")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        matiere_filtre = st.multiselect("Matière (une ou plusieurs)", toutes_matieres())
    with c2:
        niveau_filtre = st.selectbox("Niveau", ["Tous"] + TOUS_NIVEAUX)
    with c3:
        quartier_filtre = st.multiselect("Quartier / zone (un ou plusieurs)", tous_quartiers())
    with c4:
        budget_max = st.number_input("Budget max (FCFA/h)", min_value=0, value=5000, step=250)

    tri = st.radio(
        "Trier par",
        ["Pertinence", "Plus récents", "Prix croissant", "Prix décroissant"],
        horizontal=True,
    )

    avis_stats = charger_avis_stats()

    def correspond(r):
        # Multiselect vide = pas de filtre sur ce critère
        if matiere_filtre and not any(m in r["matieres"] for m in matiere_filtre):
            return False
        if niveau_filtre != "Tous" and niveau_filtre not in r["niveaux"]:
            return False
        if quartier_filtre and not any(z in r["zones_couvertes"] for z in quartier_filtre):
            return False
        if r["tarif_horaire"] > budget_max:
            return False
        if search_query:
            q = search_query.strip().lower()
            texte = " ".join([
                r["nom"], r["presentation"], " ".join(r["matieres"]), r["quartier"]
            ]).lower()
            if q not in texte:
                return False
        return True

    resultats = [r for r in repetiteurs if correspond(r)]

    if tri == "Pertinence":
        resultats.sort(key=lambda r: score_pertinence(r, avis_stats), reverse=True)
    elif tri == "Prix croissant":
        resultats.sort(key=lambda r: r["tarif_horaire"])
    elif tri == "Prix décroissant":
        resultats.sort(key=lambda r: r["tarif_horaire"], reverse=True)
    # "Plus récents" : déjà l'ordre renvoyé par charger_repetiteurs_actifs (created_at desc)

    # Pagination : on réinitialise le nombre affiché si les filtres/tri changent
    signature_filtres = (
        tuple(sorted(matiere_filtre)), niveau_filtre, tuple(sorted(quartier_filtre)),
        budget_max, tri, search_query,
    )
    if st.session_state.get("_signature_filtres") != signature_filtres:
        st.session_state._signature_filtres = signature_filtres
        st.session_state.nb_affiches = 9
    if "nb_affiches" not in st.session_state:
        st.session_state.nb_affiches = 9

    st.write("")
    if not resultats:
        st.markdown('<div class="empty">Aucun profil ne correspond à vos filtres.</div>', unsafe_allow_html=True)
    else:
        resultats_page = resultats[: st.session_state.nb_affiches]
        cols = st.columns(3)
        for i, r in enumerate(resultats_page):
            with cols[i % 3]:
                badges = "".join(f'<span class="badge">{m}</span>' for m in r["matieres"])
                badges += "".join(f'<span class="badge muted">{n}</span>' for n in r["niveaux"])
                nouveau_html = '<span class="badge nouveau">🆕 Nouveau</span>' if est_recent(r.get("created_at", "")) else ""
                message = urllib.parse.quote(
                    f"Bonjour {r['nom']}, je vous contacte via TuteurTD pour des cours particuliers."
                )
                lien_whatsapp = f"https://wa.me/{r['telephone']}?text={message}"

                if r.get("photo_url"):
                    avatar_html = f'<img src="{r["photo_url"]}" class="avatar-img" alt="{r["nom"]}">'
                else:
                    avatar_html = f'<div class="avatar">{initiales(r["nom"])}</div>'

                moyenne, nb_avis = avis_stats.get(r["id"], (0, 0))
                if nb_avis > 0:
                    note_html = f'<div class="note">⭐ {moyenne:.1f}/5 · {nb_avis} avis</div>'
                else:
                    note_html = '<div class="note muted">Pas encore d\'avis</div>'

                st.markdown(f"""
                <div class="card">
                  <div class="card-head">
                    {avatar_html}
                    <div>
                      <h3>{r['nom']}</h3>
                      <div class="meta">{r['quartier']} · {r['experience']}</div>
                    </div>
                  </div>
                  {note_html}
                  <div class="badges">{nouveau_html}{badges}</div>
                  <p class="desc">{r['presentation']}</p>
                  <div class="price">{r['tarif_horaire']:,} <span>FCFA/h</span></div>
                  <a class="btn-wa" href="{lien_whatsapp}" target="_blank" rel="noopener">💬 Contacter sur WhatsApp</a>
                </div>
                """.replace(",", " "), unsafe_allow_html=True)

                if st.button("↳ J'ai contacté ce profil", key=f"contact_{r['id']}", help="Clique ici après avoir ouvert WhatsApp — ça aide l'admin à voir les profils qui intéressent le plus"):
                    incrementer_contact(r["id"])
                    st.toast("Merci ! Bonne discussion 👋")

                avis_donnes = st.session_state.setdefault("avis_donnes", set())
                if r["id"] not in avis_donnes:
                    with st.expander("⭐ Laisser un avis"):
                        with st.form(f"form_avis_{r['id']}", clear_on_submit=True):
                            note_choisie = st.slider("Note", 1, 5, 5, key=f"note_{r['id']}")
                            commentaire = st.text_area("Commentaire (optionnel)", key=f"comm_{r['id']}")
                            if st.form_submit_button("Envoyer mon avis"):
                                if ajouter_avis(r["id"], note_choisie, commentaire):
                                    avis_donnes.add(r["id"])
                                    st.toast("Merci pour votre avis 🙏")
                                    st.rerun()
                else:
                    st.caption("✅ Avis envoyé — merci !")

        if len(resultats) > len(resultats_page):
            st.write("")
            _, col_plus, _ = st.columns([2, 1, 2])
            with col_plus:
                if st.button(f"Charger plus de profils ({len(resultats) - len(resultats_page)} restants)"):
                    st.session_state.nb_affiches += 9
                    st.rerun()

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
        st.success("✅ Profil enregistré ! Il sera visible après validation par un administrateur.")
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
        photo = st.file_uploader("Photo de profil (optionnel)", type=["jpg", "jpeg", "png"])

        submitted = st.form_submit_button("Publier mon profil")
        if submitted:
            if not nom or not telephone or not quartier or not matiere or not niveau:
                st.error("Merci de remplir tous les champs obligatoires (*).")
            else:
                photo_url = uploader_photo(photo)
                payload = {
                    "nom": nom.strip(),
                    "quartier": quartier.strip(),
                    "zones_couvertes": [quartier.strip()],
                    "matieres": [matiere.strip()],
                    "niveaux": [niveau],
                    "photo_url": photo_url,
                    "experience": experience,
                    "tarif_horaire": int(tarif),
                    "telephone": "".join(ch for ch in telephone if ch.isdigit()),
                    "presentation": bio.strip() or "Nouveau profil répétiteur.",
                    "statut": "attente",
                }
                if inserer_repetiteur(payload):
                    st.session_state.profil_ajoute = True
                    st.rerun()

    st.caption("* Champs obligatoires. Un administrateur doit valider votre profil avant qu'il soit visible.")

# ------------------------------------------------------------------
# ONGLET ADMIN
# ------------------------------------------------------------------
with tab_admin:
    admin_client = get_admin_client()

    if admin_client is None:
        st.markdown("""
        <div class="hero">
          <h2>Connexion admin</h2>
          <p>Connectez-vous avec votre compte administrateur Supabase.</p>
        </div>
        """, unsafe_allow_html=True)

        with st.form("form_admin_login"):
            email = st.text_input("Email admin")
            mot_de_passe = st.text_input("Mot de passe", type="password")
            if st.form_submit_button("Se connecter"):
                if admin_login(email, mot_de_passe):
                    st.rerun()
    else:
        col_titre, col_logout = st.columns([4, 1])
        with col_titre:
            st.markdown("""
            <div class="hero">
              <h2>Validation des profils</h2>
              <p>Activer, suspendre, contrôler la qualité des profils.</p>
            </div>
            """, unsafe_allow_html=True)
        with col_logout:
            if st.button("Déconnexion"):
                st.session_state.pop("admin_session", None)
                st.rerun()

        repetiteurs_admin = charger_repetiteurs_admin(admin_client)

        hdr = st.columns([2, 1.8, 1.8, 1.2, 1, 1.2, 1.5])
        for col, label in zip(hdr, ["Nom", "Matière", "Quartier", "Tarif", "Contacts", "Statut", "Action"]):
            col.markdown(f"**{label}**")
        st.markdown("<hr style='border-color: rgba(94,234,212,0.18); margin: 4px 0 8px;'>", unsafe_allow_html=True)

        for r in repetiteurs_admin:
            row = st.columns([2, 1.8, 1.8, 1.2, 1, 1.2, 1.5])
            row[0].write(r["nom"])
            row[1].write(", ".join(r["matieres"]))
            row[2].write(r["quartier"])
            row[3].write(f"{r['tarif_horaire']:,} F".replace(",", " "))
            row[4].write(str(r.get("nb_contacts", 0)))
            statut_class = "actif" if r["statut"] == "actif" else "attente"
            statut_label = "Actif" if r["statut"] == "actif" else "En attente"
            row[5].markdown(f'<span class="status {statut_class}">{statut_label}</span>', unsafe_allow_html=True)
            bouton_label = "Suspendre" if r["statut"] == "actif" else "Activer"
            if row[6].button(bouton_label, key=f"toggle_{r['id']}"):
                nouveau_statut = "attente" if r["statut"] == "actif" else "actif"
                if toggle_statut_admin(admin_client, r["id"], nouveau_statut):
                    st.rerun()

st.markdown(
    "<footer style='margin-top:28px;text-align:center;color:#8b9bb4;font-size:0.8rem;'>"
    "TuteurTD · Projet répétiteurs de maison · N'Djamena</footer>",
    unsafe_allow_html=True,
)
