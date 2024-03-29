#!/home/tripp/anaconda3/envs/riffdiff/bin/python3.11

import os
import sys
import json
import functools
from functools import lru_cache
import itertools
import copy

# import dependencies
import Bio
from Bio.PDB import *
import pandas as pd
import numpy as np

# import custom modules
sys.path.append("/home/tripp/riff_diff/")
import utils.adrian_utils as utils

def identify_rotamer_by_bfactor_probability(entity):
    '''
    returns the residue number where bfactor > 0, since this is where the rotamer probability was saved
    '''
    residue = None
    for atom in entity.get_atoms():
        if atom.bfactor > 0:
            residue = atom.get_parent()
            break
    if not residue:
        raise RuntimeError('Could not find any rotamer in chain. Maybe rotamer probability was set to 0?')
    resnum = residue.id[1]
    return resnum

@lru_cache(maxsize=100000000)
def distance_detection_LRU(entity1, entity2, bb_only:bool=True, ligand:bool=False, clash_detection_vdw_multiplier:float=1.0, database:str='database', resnum:int=None, covalent_bonds:str=None):
    '''
    checks for clashes by comparing VanderWaals radii. If clashes with ligand should be detected, set ligand to true. Ligand chain must be added as second entity.
    bb_only: only detect backbone clashes between to proteins or a protein and a ligand.
    clash_detection_vdw_multiplier: multiply Van der Waals radii with this value to set clash detection limits higher/lower
    database: path to database directory
    '''
    backbone_atoms = ['CA', 'C', 'N', 'O', 'H']
    vdw_radii = import_vdw_radii(database)
    if bb_only == True and ligand == False:
        entity1_atoms = (atom for atom in entity1.get_atoms() if atom.name in backbone_atoms)
        entity2_atoms = (atom for atom in entity2.get_atoms() if atom.name in backbone_atoms)
    elif bb_only == True and ligand == True:
        entity1_atoms = (atom for atom in entity1.get_atoms() if atom.name in backbone_atoms)
        entity2_atoms = (atom for atom in entity2.get_atoms())
    else:
        entity1_atoms = (atom for atom in entity1.get_atoms())
        entity2_atoms = (atom for atom in entity2.get_atoms())
    for atom_combination in itertools.product(entity1_atoms, entity2_atoms):
        #skip clash detection for covalent bonds
        covalent = False
        if resnum and covalent_bonds:
            for cov_bond in covalent_bonds.split(','):
                if atom_combination[0].get_parent().id[1] == resnum and atom_combination[0].name == cov_bond.split(':')[0] and atom_combination[1].name == cov_bond.split(':')[1]:
                    covalent = True
        if covalent == True:
            continue
        distance = atom_combination[0] - atom_combination[1]
        element1 = atom_combination[0].element
        element2 = atom_combination[1].element
        clash_detection_limit = clash_detection_vdw_multiplier * (vdw_radii[str(element1)] + vdw_radii[str(element2)])
        if distance < clash_detection_limit:
            return True
    return False

def extract_backbone_coordinates(residue):
    bb_atoms = [atom for atom in residue.get_atoms() if atom.id in ['N', 'CA', 'C', 'O']]
    coord_dict = {}
    for atom in bb_atoms:
        coord_dict[atom.id] = tuple(round(float(coord), 3) for coord in atom.get_coord())
    return coord_dict

def extract_chi_angles(residue):
    '''
    residue has to be converted to internal coords first! (on chain/model/structure level)
    '''
    chi1 = float('nan')
    chi2 = float('nan')
    chi3 = float('nan')
    chi4 = float('nan')
    resname = residue.get_resname()
    if resname in AAs_up_to_chi1() + AAs_up_to_chi2() + AAs_up_to_chi3() + AAs_up_to_chi4():
        chi1 = round(residue.internal_coord.get_angle("chi1"), 1)
    if resname in AAs_up_to_chi2() + AAs_up_to_chi3() + AAs_up_to_chi4():
        chi2 = round(residue.internal_coord.get_angle("chi2"), 1)
    if resname in AAs_up_to_chi3() + AAs_up_to_chi4():
        chi3 = round(residue.internal_coord.get_angle("chi3"), 1)
    if resname in AAs_up_to_chi4():
        chi4 = round(residue.internal_coord.get_angle("chi4"), 1)
    return {"chi1": chi1, "chi2": chi2, "chi3": chi3, "chi4": chi4}

@lru_cache(maxsize=100000)
def extract_infos(chain, resnum):
    chain.atom_to_internal_coordinates()
    rotamer = chain[resnum]
    residues = [residue for residue in chain.get_residues()]
    Nterm = residues[0]
    Cterm = residues[-1]
    #origin = f'{chain.get_parent().get_parent().id}.pdb'
    chi_angles = extract_chi_angles(rotamer)
    frag_length = len([residue for residue in chain.get_residues()])
    info = {'identity': rotamer.get_resname(), 'frag_num': chain.get_parent().id, 'res_num': resnum, 'chi1': chi_angles['chi1'], 'chi2': chi_angles['chi2'], 'chi3': chi_angles['chi3'], 'chi4': chi_angles['chi4'], 'frag_length': frag_length, 'bb_coords': {'Nterm': extract_backbone_coordinates(Nterm), 'Cterm': extract_backbone_coordinates(Cterm)}, 'rot_prob': rotamer['CA'].bfactor}
    return info

def import_vdw_radii(database_dir):
    '''
    from https://en.wikipedia.org/wiki/Atomic_radii_of_the_elements_(data_page), accessed 30.1.2023
    '''
    vdw_radii = pd.read_csv(f'{database_dir}/vdw_radii.csv')
    vdw_radii.drop(['name', 'atomic_number', 'empirical', 'Calculated', 'Covalent(sb)', 'Covalent(tb)', 'Metallic'], axis=1, inplace=True)
    vdw_radii.dropna(subset=['VdW_radius'], inplace=True)
    vdw_radii['VdW_radius'] = vdw_radii['VdW_radius'] / 100
    vdw_radii = vdw_radii.set_index('element')['VdW_radius'].to_dict()
    return vdw_radii

def AAs_up_to_chi1():
    AAs = ['CYS', 'SER', 'THR', 'VAL']
    return AAs

def AAs_up_to_chi2():
    AAs = ['ASP', 'ASN', 'HIS', 'ILE', 'LEU', 'PHE', 'PRO', 'TRP', 'TYR']
    return AAs

def AAs_up_to_chi3():
    AAs = ['GLN', 'GLU', 'MET']
    return AAs

def AAs_up_to_chi4():
    AAs = ['ARG', 'LYS']
    return AAs


def main(args):
    '''
    Combines every model from each input pdb with every model from other input pdbs. Input pdbs must only contain chain A and (optional) a ligand in chain Z.
    Checks if any combination contains clashes, and removes them.
    Writes the coordinates of N, CA, C of the central atom as well as the rotamer probability and other infos to a json file.
    '''
    if not args.json_files and not args.json_prefix:
        raise RuntimeError('Either --json_files or --json_prefix must be specified!')
    
    path, file = os.path.split(args.output_name)
    if not file.endswith('.json'):
        file += '.json'
    filename = utils.create_output_dir_change_filename(path, file)
    if os.path.exists(filename):
        raise RuntimeError(f'Output file already exists at {filename}!')

    #import json files
    input_jsons = []
    if args.json_files:
        input_jsons += [os.path.abspath(json) for json in args.json_files]
    if args.json_prefix:
        json_prefix = os.path.abspath(args.json_prefix)
        path, prefix = os.path.split(json_prefix)
        for file in os.listdir(path):
            if file.endswith('.json') and file.startswith(prefix):
                input_jsons.append(os.path.join(path, file))

    input_jsons = sorted(list(set(input_jsons)))

    #import pdbs
    inputs = []
    for file in input_jsons:
        df = pd.read_json(file)
        inputs.append(df)
    in_df = pd.concat(inputs)

    pdbs = []
    covalent_bonds = []
    rotamer_positions = []
    for pdb, df in in_df.groupby('poses'):
        pdbs.append(pdb)
        if 'covalent_bond' in df.columns:
            df['covalent_bond'].replace(np.nan, None, inplace=True)
        else:
            df['covalent_bond'] = None
        covalent_bonds.append(df['covalent_bond'].to_list())
        rotamer_positions.append([int(pos) for pos in df['rotamer_pos'].to_list()])

    database = utils.path_ends_with_slash(args.database_dir)

    chains = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y']

    structlist = [utils.import_structure_from_pdb(file) for file in pdbs]
    if len(structlist) <= 1:
        raise RuntimeError('At least 2 structures needed!')

    #delete all models that clash with the ligand
    if args.backbone_ligand_clash_detection_vdw_multiplier:
        for struct, cov_bond_list, rot_pos_list in zip(structlist, covalent_bonds, rotamer_positions):
            num_models = len([model for model in struct.get_models()])
            to_detach = []
            for model, cov_bond, resnum in zip(struct, cov_bond_list, rot_pos_list):
                check = distance_detection_LRU(model['A'], model[args.ligand_chain], bb_only=True, ligand=True, clash_detection_vdw_multiplier=args.backbone_ligand_clash_detection_vdw_multiplier, database=database, resnum=resnum, covalent_bonds=cov_bond)
                if args.rotamer_ligand_clash_detection_vdw_multiplier and check == False:
                    check = distance_detection_LRU(model['A'][resnum], model[args.ligand_chain], bb_only=False, ligand=True, clash_detection_vdw_multiplier=args.rotamer_ligand_clash_detection_vdw_multiplier, database=database, resnum=resnum, covalent_bonds=cov_bond)
                if check == True:
                    to_detach.append(model.id)


            if len(to_detach) == len([model for model in struct.get_models()]):
                raise RuntimeError(f'No model in {struct.id} found that does not clash with ligand! Maybe set covalent bonds during fragment picking or decrease VdW_multiplier?')
            if len(to_detach) > 0:
                for modelnum in to_detach:
                    struct.detach_child(modelnum)
            print(f'Deleted {len(to_detach)} of {num_models} models in {struct.id} that were clashing with ligand.')

    distance_detection_LRU.cache_clear()

    # gather all models from input structures, set chain names
    toplist = []
    for index, struct in enumerate(structlist):
        chainlist = []
        modellist = [model for model in struct.get_models()]
        for model in modellist:
            model['A'].id = chains[index]
            chainlist.append(model[chains[index]])
        toplist.append(chainlist)
    # generate every possible combination of input models
    num_models = [len(chains) for chains in toplist]
    num_combs = 1
    for i in num_models:
        num_combs *= i
    print(f'Generating {num_combs} possible combinations...')
    combinations = itertools.product(*toplist)
    #check for clashes between chains
    model_num = 0
    bb_dict = {}
    count = 0
    print(f'Performing pairwise clash detection...')
    for comb in combinations:
        #pairwise check for clash
        for chain_pair in itertools.combinations(comb, 2):
            check = distance_detection_LRU(chain_pair[0], chain_pair[1], clash_detection_vdw_multiplier=args.fragment_backbone_clash_detection_vdw_multiplier, database=database)
            if check == True:
                count = count + 1
                break
        if check == False:
            chain_dict = {}
            for chain in comb:
                model = chain.get_parent()
                struct = model.get_parent()
                df = pd.DataFrame({'poses_description': struct.id, 'model_num': model.id}, index=[0])
                df = df.merge(in_df, how='inner', on=['poses_description', 'model_num'])
                rotamer_resnum = identify_rotamer_by_bfactor_probability(chain)
                chain_dict[chain.id] = extract_infos(chain, rotamer_resnum)
                chain_dict[chain.id]['origin'] = df['poses_description'].iat[0] + '.pdb'
                if 'covalent_bond' in df.columns:
                    if not df['covalent_bond'].isnull().values.any():
                        chain_dict[chain.id]['covalent_bond'] = df['covalent_bond'].iat[0]
                    else:
                        df.drop('covalent_bond', inplace=True, axis=1)

                chain_dict[chain.id]['fragment_picking_info'] = df.drop(['model_num', 'rotamer_pos', 'poses_description', 'poses'], axis=1).to_dict(orient='records')[0]
            bb_dict[model_num] = chain_dict
            model_num = model_num + 1

    distance_detection_LRU.cache_clear()

    print(f'Deleted {count} clashing combinations.')
    print(f'Found {model_num} non-clashing combinations.')

    with open(filename, 'w') as out:
        json.dump(bb_dict, out)
        #pickle.dump(bb_dict, out)



if __name__ == "__main__":
    import argparse

    argparser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    # mandatory input
    argparser.add_argument("--database_dir", type=str, required=True, help="Path to folder containing rotamer libraries, fragment library, etc.")
    argparser.add_argument("--json_prefix", type=str, default=None, nargs='?', help="Prefix for all json files that should be combined (including path, e.g. './output/mo6_'). Alternative to --json_files")
    argparser.add_argument("--json_files", default=None, nargs='*', help="List of json files that contain fragment information. Alternative to --json_prefix.")
    argparser.add_argument("--output_name", type=str, required=True, help="Path to output file. Directory will be created if it does not exist")

    # stuff you might want to adjust
    argparser.add_argument("--fragment_backbone_clash_detection_vdw_multiplier", type=float, default=1.5, help="Multiplier for VanderWaals radii for clash detection inbetween backbone fragments. Clash is detected if distance_between_atoms < (VdW_radius_atom1 + VdW_radius_atom2)*multiplier")
    argparser.add_argument("--backbone_ligand_clash_detection_vdw_multiplier", type=float, default=1.0, help="Multiplier for VanderWaals radii for clash detection between fragment backbones and ligand. Set None if no ligand is present. Clash is detected if distance_between_atoms < (VdW_radius_atom1 + VdW_radius_atom2)*multiplier")
    argparser.add_argument("--rotamer_ligand_clash_detection_vdw_multiplier", type=float, default=0.8, help="Multiplier for VanderWaals radii for clash detection between rotamer sidechain and ligand. Clash is detected if distance_between_atoms < (VdW_radius_atom1 + VdW_radius_atom2)*multiplier")
    argparser.add_argument("--ligand_chain", type=str, default="Z", help="Name of ligand chain.")

    args = argparser.parse_args()

    main(args)
