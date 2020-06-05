import math
#from __future__ import print_function, division
#import os
import torch
import pandas as pd
import numpy as np
from torch.utils.data import Dataset
#from torchvision import transforms, utils

# Ignore warnings
import warnings
warnings.filterwarnings("ignore")


def get_gbif_data(pth, split, country):
    ## Grab GBIF observation data
    obs_pth = "{}occurrences/occurrences_{}_{}.csv".format(pth, country, split)
    return pd.read_csv(obs_pth, sep=';')  

def us_image_from_id(id_, pth, country):
    abcd = id_ % 10000
    ab, cd = math.floor(abcd/100), abcd%100
    cdd = math.ceil((cd+ 1)/5)
    cdd = "0{}".format(cdd)  if cdd < 10 else "{}".format(cdd)
    ab = "0{}".format(ab) if id_ / 1000 > 1 and ab < 10 else ab
    cd = "0{}".format(cd) if  cd < 10 else cd
    subpath = "patches_{}/patches_{}_{}/{}/{}/".format(country, country, cdd, cd, ab)
    alt = "{}{}{}_alti.npy".format(pth, subpath, id_)
    rgbd = "{}{}{}.npy".format(pth, subpath, id_)    
    np_al = np.load(alt)
    np_img = np.load(rgbd)
    np_al = np.expand_dims(np_al, 2)
    np_all = np.concatenate((np_al, np_img), axis=2)
    return np.transpose(np_all,(2, 0, 1))

def fr_img_from_id(id_, pth, country):
    abcd = id_ % 10000
    ab, cd = math.floor(abcd/100), abcd%100
    ab = "0{}".format(ab) if id_ / 1000 > 1 and ab < 10 else ab
    cd = "0{}".format(cd) if  cd < 10 else cd
    subpath = "patches_{}/{}/{}/".format(country, cd, ab)
    alt = "{}{}{}_alti.npy".format(pth, subpath, id_)
    rgbd = "{}{}{}.npy".format(pth, subpath, id_)    
    np_al = np.load(alt)
    np_img = np.load(rgbd)
    np_al = np.expand_dims(np_al, 2)
    np_all = np.concatenate((np_al, np_img), axis=2)
    return np.transpose(np_all,(2, 0, 1))
    



def add_genus_family_data(pth, us_train):
    ## getting family, genus, species ids for each observation
    # get all relevant files
    gbif_meta = pd.read_csv("{}occurrences/species_metadata.csv".format(pth), sep=";")
    taxons = pd.read_csv("{}occurrences/Taxon.tsv".format(pth), sep="\t")
    # get all unique species ids in us train data
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
    return us_train


def map_key_2_index(df, key):
    key_2_id = {
        k:v for k, v in 
        zip(df[key].unique(), np.arange(len(df[key].unique())))
    }
    df[key] = df[key].map(key_2_id)
    return df

def prep_fr_data(obs):
    raise NotImplementedError
    
def add_fr_genus_family_data(base_dir, obs):
    raise NotImplementedError

def prep_data(us_obs):

    us_obs = map_key_2_index(us_obs, 'species_id')
    us_obs = map_key_2_index(us_obs, 'genus')
    us_obs = map_key_2_index(us_obs, 'family')
    return us_obs    
    

class GEOCELF_Dataset(Dataset):
    def __init__(self, base_dir, split='train', country='us', transform=None):
        
        self.base_dir = base_dir
        self.country = country
        self.split = split
        obs = get_gbif_data(self.base_dir, split, country)
        obs = add_genus_family_data(self.base_dir, obs)
        obs = prep_data(obs)
        # Grab only obs id, species id, genus, family because lat /lon not necessary at the moment
        self.num_specs = len(obs.species_id.unique())
        self.num_fams = len(obs.family.unique())
        self.num_gens = len(obs.genus.unique())
        self.obs = obs[['id', 'species_id', 'genus', 'family']].to_numpy()
        self.transform = transform
        if self.country == 'us':
            self.channels = us_image_from_id(self.obs[0,0], self.base_dir, self.country).shape[0]
        elif self.country == 'fr':
            self.channels = fr_img_from_id(self.obs[0,0], self.base_dir, self.country).shape[0]
        else:
            exit(1), "improper country id specified!"

    def __len__(self):
        return len(self.obs)

    def __getitem__(self, idx):
        if torch.is_tensor(idx):
            idx = idx.tolist()
        # obs is of shape [id, species_id, genus, family]    
        id_, label = self.obs[idx, 0], self.obs[idx, 1]
        images = us_image_from_id(id_, self.base_dir, self.country) if self.country == 'us' else fr_img_from_id(id_, self.base_dir, self.country) 
        composite_label = self.obs[idx, 1:] # get genus, family as well
        if self.transform:
            images = self.transform(images)
        return (composite_label, images)


    
    
class GEOCELF_Test_Dataset(Dataset):
    def __init__(self, base_dir, split = 'test', country='us', transform=None):
        
        self.base_dir = base_dir
        self.country = country
        self.split = split
        obs = get_gbif_data(self.base_dir, split, country)
        self.obs = obs[['id']].to_numpy()
        self.transform = transform

    def __len__(self):
        return len(self.obs)

    def __getitem__(self, idx):
        if torch.is_tensor(idx):
            idx = idx.tolist()
        # obs is of shape [id, species_id, genus, family]    
        id_ = self.obs[idx, 0]
        images = us_image_from_id(id_, self.base_dir, self.country) if self.country == 'us' else fr_img_from_id(id_, self.base_dir, self.country) 

#         composite_label = self.obs[idx, 1:] # get genus, family as well
        if self.transform:
            images = self.transform(images)
        return images

    
    
    
class GEOCELF_Cali_Dataset(Dataset):
    def __init__(self, base_dir, country, transform=None):
        

        obs = pd.read_csv("{}occurrences/occurrences_cali_filtered.csv".format(base_dir))
        obs = prep_US_data(obs)
        # Grab only obs id, species id, genus, family because lat /lon not necessary at the moment
        self.base_dir = base_dir
        self.country = country
        self.num_specs = len(obs.species_id.unique())
        self.num_fams = len(obs.family.unique())
        self.num_gens = len(obs.genus.unique())
        self.obs = obs[['id', 'species_id', 'genus', 'family']].to_numpy()
        self.transform = transform
        self.channels = us_image_from_id(self.obs[0,0], self.base_dir, self.country).shape[0]

    def __len__(self):
        return len(self.obs)

    def __getitem__(self, idx):
        if torch.is_tensor(idx):
            idx = idx.tolist()
        # obs is of shape [id, species_id, genus, family]    
        id_, label = self.obs[idx, 0], self.obs[idx, 1]
        images = us_image_from_id(id_, self.base_dir, self.country) 
        composite_label = self.obs[idx, 1:] # get genus, family as well
        if self.transform:
            images = self.transform(images)
        return (composite_label, images)

    def num_cats(self):
        return self.num_cats
    def num_channels(self):
        return self.channels
    
    
    
    
class GEOCELF_Cali_Dataset_Tiny(Dataset):
    def __init__(self, base_dir, country, transform=None):
        

        obs = pd.read_csv("{}occurrences/occurrences_cali_filtered.csv".format(base_dir))
        obs = obs[:1000]
        obs = prep_US_data(obs)
        # Grab only obs id, species id, genus, family because lat /lon not necessary at the moment
        self.base_dir = base_dir
        self.country = country
        self.num_specs = len(obs.species_id.unique())
        self.num_fams = len(obs.family.unique())
        self.num_gens = len(obs.genus.unique())
        self.obs = obs[['id', 'species_id', 'genus', 'family']].to_numpy()
        self.transform = transform
        self.channels = us_image_from_id(self.obs[0,0], self.base_dir, self.country).shape[0]

    def __len__(self):
        return len(self.obs)

    def __getitem__(self, idx):
        if torch.is_tensor(idx):
            idx = idx.tolist()
        # obs is of shape [id, species_id, genus, family]    
        id_, label = self.obs[idx, 0], self.obs[idx, 1]
        images = us_image_from_id(id_, self.base_dir, self.country) 
        composite_label = self.obs[idx, 1:] # get genus, family as well
        if self.transform:
            images = self.transform(images)
        return (composite_label, images)

    def num_cats(self):
        return self.num_cats
    def num_channels(self):
        return self.channels    
    
    
class GEOCELF_Dataset_Full(Dataset):
    def __init__(self, base_dir, split='train', transform=None):
        
        self.base_dir = base_dir
        self.split = split
        us_obs = get_gbif_data(self.base_dir, split, 'us')
        fr_obs = get_gbif_data(self.base_dir, split, 'fr')
        obs = pd.concat([us_obs, fr_obs])
        obs = add_genus_family_data(self.base_dir, obs)
        obs = prep_data(obs)
        # Grab only obs id, species id, genus, family because lat /lon not necessary at the moment
        self.num_specs = len(obs.species_id.unique())
        self.num_fams = len(obs.family.unique())
        self.num_gens = len(obs.genus.unique())
        self.obs = obs[['id', 'species_id', 'genus', 'family']].to_numpy()
        self.transform = transform
        id_ = int(us_obs.to_numpy()[0,0])
        self.channels = us_image_from_id(id_, self.base_dir, 'us').shape[0]

    def __len__(self):
        return len(self.obs)

    def __getitem__(self, idx):
        if torch.is_tensor(idx):
            idx = idx.tolist()
        # obs is of shape [id, species_id, genus, family]    
        id_, label = self.obs[idx, 0], self.obs[idx, 1]
        images = fr_img_from_id(id_, self.base_dir, 'fr')  if id_ >= 10000000 else us_image_from_id(id_, self.base_dir, 'us')

        composite_label = self.obs[idx, 1:] # get genus, family as well
        if self.transform:
            images = self.transform(images)
        return (composite_label, images)