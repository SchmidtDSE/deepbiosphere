from random import randrange
import pandas as pd
import argparse
import numpy as np
import random
import math
from deepbiosphere.scripts import GEOCELF_CNN as cnn
from deepbiosphere.scripts import GEOCELF_Dataset as Dataset
from deepbiosphere.scripts import paths
from pygeocoder import Geocoder
import reverse_geocoder as rg
print("getting data")
pth = paths.DBS_DIR
us_train_pth = f"{pth}occurrences/occurrences_us_train.csv"
us_train = pd.read_csv(us_train_pth, sep=';')
print("filtering by state")
# create a new tuple column
us_train['lat_lon'] = list(zip(us_train.lat, us_train.lon))
# convert to list for faster exraction
us_latlon = us_train['lat_lon'].tolist()
# grab location data for the lat lon
res = rg.search(us_latlon)
# grab only the states from the results
states = [r['admin1'] for r in res]
# add the states information back into the original dataframe
us_train['state'] = states
# grab only observations from california
filtered_us = us_train[us_train.state == 'California']



## getting family, genus, species ids for each observation
# get all relevant files
print("adding taxon information")
gbif_meta = pd.read_csv(f"{pth}occurrences/species_metadata.csv", sep=";")
taxons = pd.read_csv(f"{pth}occurrences/Taxon.tsv", sep="\t")
# get all unique species ids in filtered train data
us_celf_spec = filtered_us.species_id.unique()
# get all the gbif species ids for all the species in the us sample
conversion = gbif_meta[gbif_meta['species_id'].isin(us_celf_spec)]
gbif_specs = conversion.GBIF_species_id.unique()
# get dict that maps CELF id to GBIF id
spec_2_gbif = dict(zip(conversion.species_id, conversion.GBIF_species_id))
filtered_us['gbif_id'] = filtered_us['species_id'].map(spec_2_gbif)
# grab all the phylogeny mappings from the gbif taxons file for all the given species
# GBIF id == taxonID
taxa = taxons[taxons['taxonID'].isin(gbif_specs)]
phylogeny = taxa[['taxonID', 'kingdom', 'phylum', 'class', 'order', 'family', 'genus']]
gbif_2_fam = dict(zip(phylogeny.taxonID, phylogeny.family))
gbif_2_gen = dict(zip(phylogeny.taxonID, phylogeny.genus))
filtered_us['family'] = filtered_us['gbif_id'].map(gbif_2_fam)
filtered_us['genus'] = filtered_us['gbif_id'].map(gbif_2_gen)
# grab only relevant data for training
print("saving to file")
filtered_us[['id','species_id', 'genus', 'family']].to_csv(f"{pth}/occurrences/occurrences_cali_filtered.csv")