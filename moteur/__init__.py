"""Moteur de prospection par email, multi-clients, sans abonnement tiers.

Un dossier par client dans clients/<nom>/ :
  client.json   la fiche (cible, offre, boîte d'envoi, cadence)   -> écrite par le pilote
  decisions/    les décisions à appliquer (valider, refuser...)   -> écrites par le pilote
  etat.json     tout ce que le moteur sait et a fait              -> écrit par le moteur seul
  espace/       la page de suivi du client                        -> écrite par le moteur seul
"""
__version__ = "1.0"
