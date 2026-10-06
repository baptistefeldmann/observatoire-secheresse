# Accès distant : QGIS sur un poste Windows

Le dépôt, PostGIS et les rasters tournent sur la machine Linux. QGIS tourne sur un poste Windows qui se connecte à cette machine en SSH.

Le poste Windows n'a besoin que de trois choses :

| Besoin | Source | Accès depuis Windows |
|---|---|---|
| Couches vectorielles | PostGIS (machine Linux) | tunnel SSH, port 5433 |
| Rasters COG [V2] | `rasters/` servi par l'API (machine Linux) | tunnel SSH, port 8010 |
| Projet `.qgz` et styles | dossier `qgis/` du dépôt | clone Git |

PostGIS n'écoute que sur la machine Linux elle-même (`POSTGRES_BIND=127.0.0.1`) : aucun port n'est ouvert sur le réseau, SSH assure l'authentification et le chiffrement.

Les exemples utilisent le service `secheresse_vendee` ; pour un autre territoire, remplacer par `secheresse_<slug>`.

## 1. Côté Linux (une fois)

```bash
cp .env.example .env     # renseigner POSTGRES_PASSWORD et POSTGRES_LECTEUR_PASSWORD
make up
```

Le rôle `lecteur` (lecture seule) est créé à la première initialisation du volume. Si le volume existait déjà, ou après un changement de `POSTGRES_LECTEUR_PASSWORD` : `make db-roles`.

## 2. Côté Windows (une fois)

### Tunnel SSH

Le client OpenSSH est inclus dans Windows 10 et 11. Ajouter dans `C:\Users\<vous>\.ssh\config` :

```
# Accès simple (git, shell)
Host secheresse
    HostName <adresse de la machine Linux>
    User <utilisateur>

# Tunnel vers PostGIS et l'API
Host secheresse-tunnel
    HostName <adresse de la machine Linux>
    User <utilisateur>
    ServerAliveInterval 60
    ExitOnForwardFailure yes
    LocalForward 5433 localhost:5433
    LocalForward 8010 localhost:8010
```

Deux entrées distinctes : sinon chaque `git pull` tenterait de rouvrir les redirections et échouerait tant que le tunnel est ouvert.

`ExitOnForwardFailure` fait échouer la connexion de façon explicite si un port local est déjà occupé sur le portable ; dans ce cas, changer le premier numéro de `LocalForward` et le `port` du fichier de service ci-dessous.

### Fichier de service PostgreSQL

1. Copier `qgis/pg_service.conf.example` en `C:\Users\<vous>\pg_service.conf`.
2. Déclarer son emplacement, dans PowerShell :

   ```powershell
   setx PGSERVICEFILE "$env:USERPROFILE\pg_service.conf"
   ```

### Mot de passe

Créer `%APPDATA%\postgresql\pgpass.conf` (créer le dossier `postgresql` s'il n'existe pas) avec une ligne :

```
localhost:5433:secheresse_vendee:lecteur:<POSTGRES_LECTEUR_PASSWORD>
```

On préfère `pgpass` à une configuration d'authentification QGIS : cette dernière inscrit un identifiant propre au poste (`authcfg=...`) dans la source de chaque couche, ce qui rend le projet versionné inutilisable sur un autre poste. Avec `pgpass`, la source des couches ne contient que `service=secheresse_vendee`.

### Projet QGIS

Cloner le dépôt depuis la machine Linux (ou depuis DagsHub une fois le remote configuré) :

```powershell
git clone ssh://secheresse/<chemin du dépôt sur la machine Linux>
```

Sur le portable servent le dossier `qgis/` et la configuration (`config/`, lue par le script de génération du projet) ; `git pull` récupère les mises à jour. Génération et ouverture du projet : [README, section 6.2](../README.md#62-générer-le-projet).

## 3. À chaque session

1. Ouvrir le tunnel dans un PowerShell, et le laisser ouvert :

   ```powershell
   ssh -N secheresse-tunnel
   ```

2. Vérifier, si besoin, dans un autre PowerShell :

   ```powershell
   Test-NetConnection localhost -Port 5433
   ```

3. Ouvrir QGIS (redémarré après le `setx`). Première fois seulement : Explorateur › PostgreSQL › Nouvelle connexion, nom `secheresse_vendee`, champ **Service** = `secheresse_vendee`, laisser hôte, port, base et authentification vides, puis « Tester la connexion ».

## Rasters [V2]

Une fois l'API en place, elle servira le dossier `rasters/` en HTTP sur le port 8010. QGIS lit un COG directement par son URL (Couche › Ajouter une couche raster › Protocole HTTP) :

```
/vsicurl/http://localhost:8010/rasters/<fichier>.tif
```

Seules les tuiles affichées sont téléchargées. Pour un calcul lourd (statistiques zonales sur tout le département), télécharger d'abord le fichier en local.
