# Vérification préliminaire de conformité au PLU (prototype MBA)

1. Importer le règlement du PLU (PDF).
2. Décrire le projet (secteur, type de construction).
3. Obtenir les règles : le règlement de la zone UB d'Éragny-sur-Oise est reconnu par son empreinte et utilise les règles vérifiées ;
   tout autre PDF passe par le pipeline complet (OCR Tesseract, découpage par article, recherche sémantique (plongements Gemini en ligne ; bge-m3 dans le notebook), extraction Gemini avec garde-fous).
4. Répondre au questionnaire.
5. Lire le rapport : chaque point cite l'article, la page et l'extrait du PLU.

Le modèle de langage ne décide jamais de la conformité : l'applicabilité et la conformité sont calculées par du code
(cellules 18 et 29 du notebook, reprises telles quelles dans les fichiers c18.py et c29.py).

Clé Gemini : à ajouter dans les *Secrets* de l'application Streamlit sous la forme `GEMINI_API_KEY = "..."`
(seulement nécessaire pour un nouveau document ou un autre secteur que UB).
