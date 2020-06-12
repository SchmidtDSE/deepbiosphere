from random import randrange
import pandas as pd
import argparse
import time
import numpy as np
import socket
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from torch.utils.data import DataLoader
from torch.utils.data.sampler import SubsetRandomSampler
import random
import math 
import reverse_geocoder as rg
from tqdm import tqdm
from deepbiosphere.scripts import GEOCELF_CNN as cnn
from deepbiosphere.scripts import GEOCELF_Dataset as Dataset
from deepbiosphere.scripts import paths

# https://www.movable-type.co.uk/scripts/latlong.html
def nmea_2_meters(lat1, lon1, lat2, lon2):
    
    R = 6371009 #; // metres
    r1 = lat1 * math.pi/180 #; // φ, λ in radians
    r2 = lat2 * math.pi/180;
    dr = (lat2-lat1) * math.pi/180;
    dl = (lon2-lon1) * math.pi/180;

    a = math.sin(dr/2) * math.sin(dr/2) + \
              math.cos(r1) * math.cos(r2) * \
              math.sin(dl/2) * math.sin(dl/2);
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a));

    d = R * c #; // in metres
    return d



def get_joint_from_group(group_df):
    df_np = group_df[['lat', 'lon', 'species_id', 'gbif_id', 'family', 'genus']].to_numpy()
    extra_specs = [{df_np[i,2]} for i in range(len(df_np))]
    extra_fams = [{df_np[i,4]} for i in range(len(df_np))] 
    extra_gens = [{df_np[i,5]} for i in range(len(df_np))]
    
    tick = time.time()
    # def nmea_2_meters(lat1, lon1, lat2, lon2):
    for i in range(len(df_np)):
        for j in range(len(df_np)):
            if i != j:
                dist = nmea_2_meters(df_np[i,0], df_np[i,1], df_np[j,0], df_np[j,1])
                if dist <= 256:
                    extra_specs[i].add(df_np[j,2])
                    extra_fams[i].add(df_np[j,4])
                    extra_gens[i].add(df_np[j,5])
    tock = time.time()                
    diff = tock - tick
    # ((diff / len(bb_np)) * len(filtered))/(60*60)
    print(f"took {diff} seconds")
    group_df['all_specs'] = extra_specs
    group_df['all_fams'] = extra_fams
    group_df['all_gens'] = extra_gens    
    return group_df


def main():
    print("grab data")
    pth = ARGS.base_dir
    us_train = None
    if ARGS.filtered:
        us_train = pd.read_csv(f"{pth}/occurrences/occurrences_cali_filtered_full.csv")
    else:
        us_train_pth = f"{pth}occurrences/occurrences_{ARGS.country}_train.csv"
        us_train = pd.read_csv(us_train_pth, sep=';')
        
    gbif_meta = pd.read_csv("{}occurrences/species_metadata.csv".format(pth), sep=";")
    taxons = pd.read_csv("{}occurrences/Taxon.tsv".format(pth), sep="\t")
    us_train.fillna('nan', inplace = True)
    us_celf_spec = us_train.species_id.unique()
    # get all the gbif species ids for all the species in the us sample
    conversion = gbif_meta[gbif_meta['species_id'].isin(us_celf_spec)]
    gbif_specs = conversion.GBIF_species_id.unique()
    # get dict that maps CELF id to GBIF id
    spec_2_gbif = dict(zip(conversion.species_id, conversion.GBIF_species_id))
    us_train['gbif_id'] = us_train['species_id'].map(spec_2_gbif)
    # grab all the phylogeny mappings from the gbif taxons file for all the given species
    # GBIF id == taxonID
    taxa = taxons[taxons['taxonID'].isin(gbif_specs)]
    phylogeny = taxa[['taxonID', 'kingdom', 'phylum', 'class', 'order', 'family', 'genus']]
    gbif_2_fam = dict(zip(phylogeny.taxonID, phylogeny.family))
    gbif_2_gen = dict(zip(phylogeny.taxonID, phylogeny.genus))
    us_train['family'] = us_train['gbif_id'].map(gbif_2_fam)
    us_train['genus'] = us_train['gbif_id'].map(gbif_2_gen)
    
    # create a new tuple column
    us_train['lat_lon'] = list(zip(us_train.lat, us_train.lon))
    # convert to list for faster extraction
    us_latlon = us_train['lat_lon'].tolist()
    # grab location data for the lat lon
    res = rg.search(us_latlon)
    # grab necessary info from the results
    states = [r['admin1'] for r in res]
    regions = [r['admin2'] for r in res]
    cities = [r['name'] for r in res]
    # add the states information back into the original dataframe
    us_train['state'] = states
    us_train['region'] = regions
    us_train['city'] = cities
    # group data into smaller, more manageable chunks
    grouped = us_train.groupby(['city', 'state', 'region'])
    all_datframes = []
    for (grouping, df) in grouped:
        print(f"grouping {grouping}")
        joint_df = get_joint_from_group(df)

        if not ARGS.filtered:
            write_pth = f"{pth}joint_obs/"
            city = grouping[0].replace(" ", "")
            region = grouping[2].replace(" ", "")
            state = grouping[1].replace(" ", "")
            pth_pth = f"{write_pth}{ARGS.country}_{city}_{region}_{state}.csv"
#             print(f"saving to {pth_pth}")
            joint_df.to_csv(pth_pth)
        else:     
            all_datframes.append(joint_df)

    if ARGS.filtered:
        joint_obs = pd.concat(all_datframes)
        print("save data")
        region = 'cali' if ARGS.filtered else ARGS.country
        joint_obs.to_csv(f"{pth}/occurrences/joint_obs_{region}.csv")
    
    
if __name__ == "__main__":
    #print(f"torch version: {torch.__version__}") 
    #print(f"numpy version: {np.__version__}")
    print("hello")
    parser = argparse.ArgumentParser()
    parser.add_argument("--country", type=str, help="which country's images to read", default='us', required=True, choices=['us', 'fr'])
    parser.add_argument("--base_dir", type=str, help="what folder to read images from",choices=['DBS_DIR', 'MEMEX_LUSTRE', 'CALC_SCRATCH', 'AZURE_DIR'], required=True)
    parser.add_argument('--filtered', dest='filtered', help="if using cali filtered data", action='store_true')
    ARGS, _ = parser.parse_known_args()
    ARGS.base_dir = eval("paths.{}".format(ARGS.base_dir))
    print("using base directory {}".format(ARGS.base_dir))
    main()
