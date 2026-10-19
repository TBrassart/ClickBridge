# Checklist de validation ClickBridge

Cette checklist est à suivre après une nouvelle installation ou une mise à jour. Elle décrit des vérifications manuelles : coche une case uniquement après l’avoir réalisée. Les tests du Zwift Ride nécessitent les deux unités physiques.

## Avant de commencer

- [ ] Noter la version affichée dans **Configuration** (version à valider : **v1.0.7**).
- [ ] Noter la version de Windows et le type d’adaptateur Bluetooth utilisé.
- [ ] Fermer Zwift et les autres applications qui pourraient déjà utiliser les appareils.
- [ ] Vérifier que le Bluetooth Windows est activé et que les appareils sont chargés.

## Installation et interface

- [ ] Installer ClickBridge depuis la [release officielle](https://github.com/TBrassart/ClickBridge/releases/tag/v1.0.7), puis lancer l’application.
- [ ] Vérifier que la fenêtre s’ouvre sans erreur et que **Configuration** et **Journal** sont accessibles.
- [ ] Sélectionner **Zwift Click V1**, puis **Zwift Ride** : les unités Ride gauche et droite doivent rester groupées.
- [ ] En mode Ride, vérifier que les deux panneaux, les boutons, les statistiques et le pied de fenêtre restent visibles, sans ascenseur.
- [ ] Changer plusieurs fois d’équipement et de profil ; vérifier que la sélection reste correcte.

## Zwift Click V1

- [ ] Réveiller le Click près du PC et vérifier que ClickBridge le détecte et se connecte.
- [ ] Appuyer sur + et − ; vérifier l’indication visuelle, l’action du profil actif et les compteurs.
- [ ] Vérifier le niveau de batterie s’il est transmis par l’appareil.
- [ ] Éteindre le Click ou couper le Bluetooth : l’application doit rester ouverte et signaler la perte de connexion.
- [ ] Rallumer le Click ou réactiver le Bluetooth : vérifier que la recherche reprend et que la reconnexion se fait.

## Zwift Ride (si les deux unités sont disponibles)

- [ ] Réveiller les unités gauche et droite et vérifier leur détection séparée dans le même écran Ride.
- [ ] Tester les commandes directionnelles de gauche, les boutons A/B/Y/Z de droite et les deux leviers.
- [ ] Vérifier les indicateurs d’appui, les valeurs de batterie et le compteur **Appuis Ride**.
- [ ] Tester avec une unité éteinte, puis la réveiller ; l’autre unité et l’application doivent rester utilisables.
- [ ] Mettre Windows en veille, reprendre la session et vérifier la recherche/reconnexion des deux unités.

> Le Zwift Ride reste expérimental. Si tu ne disposes pas des appareils, laisse ces cases décochées et indique « non testé » dans le compte rendu.

## Profils, diagnostic et réglages

- [ ] Vérifier que **Automatique** applique le profil par défaut et qu’un profil sélectionné manuellement reste actif.
- [ ] Démarrer puis arrêter une session ; contrôler durée, compteurs, moyenne et entrée dans **Historique**.
- [ ] Exporter un diagnostic en laissant l’anonymisation activée et la configuration complète ainsi que les trames brutes désactivées.
- [ ] Ouvrir l’archive et vérifier son contenu avant tout partage public.
- [ ] Exporter puis importer une configuration de test ; vérifier que les profils et réglages attendus sont présents.
- [ ] Tester **Restaurer les paramètres par défaut** uniquement si souhaité ; vérifier qu’une sauvegarde est créée.
- [ ] Si les options Windows sont utilisées, vérifier le démarrage automatique et le démarrage minimisé dans la zone de notification.

## Compte rendu

Pour tout échec, noter la version, Windows, l’équipement testé, les étapes, le résultat attendu et le résultat observé. Joindre un diagnostic anonymisé après avoir vérifié son contenu. Les tickets sont publics : ne pas publier d’adresse Bluetooth, de chemin personnel ni de configuration privée.

Signaler le problème dans les [GitHub Issues de ClickBridge](https://github.com/TBrassart/ClickBridge/issues/new/choose). Voir aussi [Aide et dépannage](SUPPORT.md).
