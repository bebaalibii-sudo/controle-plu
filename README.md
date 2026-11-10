# Vérification préliminaire de conformité au PLU (prototype MBA)

Importez le règlement de n'importe quel PLU (PDF), décrivez le projet, et obtenez un rapport article par article, avec la page et l'extrait exact du règlement.

1. Importer le règlement du PLU (PDF), de n'importe quelle commune et zone.
2. Décrire le projet (secteur, type de construction).
3. Le pipeline lit le document : OCR Tesseract, découpage par article, recherche sémantique (plongements Gemini), extraction de 7 paramètres par Gemini avec garde-fous (citation, nombre et page vérifiés dans le texte).
4. Répondre au questionnaire.
5. Lire le rapport : chaque point cite l'article, la page et l'extrait du PLU.

Le modèle de langage ne décide jamais de la conformité : l'applicabilité et la conformité sont calculées par du code (cellules 18 et 29 du notebook, fichiers c18.py et c29.py).

Raccourci : le règlement de la zone UB d'Éragny-sur-Oise, analysé pendant le projet, est reconnu automatiquement et utilise les règles vérifiées à la main.

Limite : le découpage attend des articles numérotés (« ARTICLE UA.1 », « ARTICLE UB.6 »…). Un règlement organisé autrement est signalé.

Clé Gemini : à ajouter dans les Secrets de l'application Streamlit sous la forme GEMINI_API_KEY = "...".
