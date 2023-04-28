#!/home/mabr3112/anaconda3/bin/python3.9
import sys
sys.path.append("/home/mabr3112/riff_diff")
sys.path += ["/home/mabr3112/projects/iterative_refinement/"]
sys.path += ["/home/markus/Desktop/script_development/iterative_refinement/"]

import json
from glob import glob
import os
import pandas as pd
import shutil

# import custom modules
from iterative_refinement import *
import utils.plotting as plots 
import utils.biopython_tools
import utils.pymol_tools
from utils.plotting import PlottingTrajectory
import utils.metrics as metrics
import superimposition_tools

def fr_mpnn_esmfold(poses, prefix:str, n:int, index_layers_to_reference:int=0, fastrelax_pose_opts="fr_pose_opts", ref_pdb_dir:str=None) -> Poses:
    '''AAA'''
    # run fastrelax on predicted poses
    fr_opts = f"-beta -parser:protocol {args.refinement_protocol}"
    fr = poses.rosetta("rosetta_scripts.default.linuxgccrelease", options=fr_opts, pose_options=poses.poses_df[fastrelax_pose_opts].to_list(), n=n, prefix=f"{prefix}_refinement")
    
    # calculate RMSDs and filter
    rmsds = poses.calc_motif_bb_rmsd_dir(ref_pdb_dir=ref_pdb_dir, ref_motif=poses.poses_df["template_motif"].to_list(), target_motif=poses.poses_df["motif_residues"].to_list(), metric_prefix=f"{prefix}_refinement_bb_ca", remove_layers=index_layers_to_reference+1)
    fr_comp_score = poses.calc_composite_score(f"{prefix}_fr_comp_score", [f"{prefix}_refinement_total_score", f"{prefix}_refinement_bb_ca_motif_rmsd"], [1,1])
    fr_filter = poses.filter_poses_by_score(2, f"{prefix}_fr_comp_score", remove_layers=1, prefix=f"{prefix}_refinement_filter", plot=[f"{prefix}_refinement_total_score", f"{prefix}_refinement_bb_ca_motif_rmsd"])

    # design and predict:
    poses, index_layers = mpnn_design_and_esmfold(poses, prefix=prefix, index_layers_to_reference=index_layers_to_reference+1, num_mpnn_seqs=48, num_esm_inputs=16, num_esm_outputs_per_input_backbone=5, ref_pdb_dir=ref_pdb_dir, bb_rmsd_dir=fr, rmsd_weight=3)
    return poses, index_layers_to_reference + 2

def mpnn_fr(poses, prefix:str, index_layers_to_reference:int=0, fastrelax_pose_opts="fr_pose_opts", pdb_location_col:str=None, ref_pdb_dir:str=None, reference_location_col="input_poses"):
    '''AAA'''
    def collapse_dict_values(in_dict: dict) -> str:
        return ",".join([str(y) for x in in_dict.values() for y in list(x)])
    def write_pose_opts(row: pd.Series, mpnn_col:str, reference_location_col:str="input_poses") -> str:
        return f"-in:file:native {row[reference_location_col]} -parser:script_vars seq={row[mpnn_col]} motif_res={collapse_dict_values(row['motif_residues'])} cat_res={collapse_dict_values(row['fixed_residues'])}"

    # mpnn design on backbones
    mpnn_designs = poses.mpnn_design(mpnn_options=f"--num_seq_per_target=1 --sampling_temp=0.05", prefix=f"{prefix}_mpnn", fixed_positions_col="fixed_residues")
    
    # write pose_opts (because sequence changes every time!!!)
    mpnn_col = f"{prefix}_mpnn_sequence"
    poses.poses_df[fastrelax_pose_opts] = [write_pose_opts(row, mpnn_col, reference_location_col=reference_location_col) for index, row in poses.poses_df.iterrows()]

    # fastrelax
    fr_opts = f"-beta -parser:protocol {args.fastrelax_protocol}"
    poses.poses_df["poses"] = poses.poses_df[pdb_location_col]
    poses.poses_df["poses_description"] = poses.poses_df["poses"].str.split("/").str[-1].str.replace(".pdb","")
    fr = poses.rosetta("rosetta_scripts.default.linuxgccrelease", options=fr_opts, pose_options=poses.poses_df[fastrelax_pose_opts].to_list(), n=1, prefix=f"{prefix}_fr")
    if ref_pdb_dir:
        fr_motif_ca_rmsds = poses.calc_motif_bb_rmsd_dir(ref_pdb_dir=ref_pdb_dir, ref_motif=poses.poses_df["template_motif"].to_list(), target_motif=poses.poses_df["motif_residues"].to_list(), metric_prefix=f"{prefix}_fr_bb_ca", remove_layers=index_layers_to_reference+1)

    return poses, index_layers_to_reference+1, fr

def mpnn_design_and_esmfold(poses, prefix:str, index_layers_to_reference:int=0, num_mpnn_seqs:int=20, num_esm_inputs:int=8, num_esm_outputs_per_input_backbone:int=1, ref_pdb_dir:str=None, bb_rmsd_dir:str=None, rmsd_weight:float=1):
    '''AAA'''
    # Run MPNN and filter (by half)
    mpnn_designs = poses.mpnn_design(mpnn_options=f"--num_seq_per_target={num_mpnn_seqs} --sampling_temp=0.1", prefix=f"{prefix}_mpnn", fixed_positions_col="fixed_residues")
    mpnn_seqfilter = poses.filter_poses_by_score(num_esm_inputs, f"{prefix}_mpnn_score", prefix=f"{prefix}_mpnn_seqfilter", remove_layers=1)

    # Run ESMFold and calc bb_ca_rmsd, motif_ca_rmsd and motif_heavy RMSD
    esm_preds = poses.predict_sequences(run_ESMFold, prefix=f"{prefix}_esm")
    esm_bb_ca_rmsds = poses.calc_bb_rmsd_dir(ref_pdb_dir=bb_rmsd_dir, metric_prefix=f"{prefix}_esm", ref_chains=["A"], pose_chains=["A"], remove_layers=1)
    esm_motif_rmsds = poses.calc_motif_bb_rmsd_dir(ref_pdb_dir=ref_pdb_dir, ref_motif=list(poses.poses_df["template_motif"]), target_motif=list(poses.poses_df["motif_residues"]), metric_prefix=f"{prefix}_esm_bb_ca", remove_layers=index_layers_to_reference+1)
    esm_motif_heavy_rmsds = poses.calc_motif_heavy_rmsd_dir(ref_pdb_dir=ref_pdb_dir, ref_motif=poses.poses_df["template_fixedres"].to_list(), target_motif=poses.poses_df["fixed_residues"].to_list(), metric_prefix=f"{prefix}_esm_catres", remove_layers=index_layers_to_reference+1)

    # Filter Redesigns based on confidence and RMSDs
    esm_comp_score = poses.calc_composite_score(f"{prefix}_esm_comp_score", [f"{prefix}_esm_plddt", f"{prefix}_esm_bb_ca_motif_rmsd"], [-1, rmsd_weight])
    esm_filter = poses.filter_poses_by_score(num_esm_outputs_per_input_backbone, f"{prefix}_esm_comp_score", remove_layers=1, prefix=f"{prefix}_esm_filter", plot=[f"{prefix}_esm_comp_score", f"{prefix}_esm_plddt", f"{prefix}_esm_bb_ca_rmsd", f"{prefix}_esm_bb_ca_motif_rmsd", f"{prefix}_esm_catres_motif_heavy_rmsd"])
    
    # Plot Results
    if not os.path.isdir((plotdir := f"{poses.dir}/plots")): os.makedirs(plotdir, exist_ok=True)

    # ESM stats:
    cols = [f"{prefix}_esm_plddt", f"{prefix}_esm_bb_ca_rmsd", f"{prefix}_esm_bb_ca_motif_rmsd", f"{prefix}_esm_catres_motif_heavy_rmsd"]
    titles = ["ESM pLDDT", "ESM BB-Ca RMSD", "ESM Motif-Ca RMSD", "ESM Catres\nSidechain RMSD"]
    y_labels = ["pLDDT", "RMSD [\u00C5]", "RMSD [\u00C5]", "RMSD [\u00C5]"]
    dims = [(0,100), (0,15), (0,8), (0,8)]
    _ = plots.violinplot_multiple_cols(poses.poses_df, cols=cols, titles=titles, y_labels=y_labels, dims=dims, out_path=f"{plotdir}/{prefix}_esm_stats.png")
    return poses, index_layers_to_reference+1

def convert_sampled_mask(old_contig):
    '''converts sampled mask output of RFDiffusion into new motif'''
    def parse_filler(elem):
        return [x for x in elem.split("-") if x][-1]
    def parse_contig_elem(elem, counter):
        start, end = [int(x) for x in elem[1:].split("-")]
        return end+counter, f"A{start+counter}-{end+counter}"
    
    contig_elems = old_contig[0].split("/") if type(old_contig) == list else old_contig.split("/")
    new_contig_list = list()
    counter = 0
    
    for elem in contig_elems:
        if elem[0].isalpha():
            counter, sub_contig = parse_contig_elem(elem, counter)
            new_contig_list.append(sub_contig)
        else:
            new_contig_list.append((num := parse_filler(elem)))
            counter += int(num)
            
    return "/".join(new_contig_list)

def create_inpaint_seq(contig, motif):
    '''AAA'''
    def parse_inpaint_substr(elem, fixedres) -> str:
        inpaint_str_l = list()
        start, end = [int(x) for x in elem[1:].split("-")]
        for i in range(start, end+1):
            inpaint_str_l.append(elem[0]+str(i))
        return [x for x in inpaint_str_l if x not in fixedres]
    
    # split contigs, start list
    contig_elems = contig.split("/")
    inpaint_str_list = list()
    
    # assemble fixed_residues:
    fixed_res = [str(k)+str(idx) for k, v in motif.items() for idx in v]
    
    # assemble inpaint_seq piece by piece
    for elem in contig_elems:
        if elem[0].isalpha():
            [inpaint_str_list.append(x) for x in parse_inpaint_substr(elem, fixed_res)]
    return "/".join(inpaint_str_list)

def divide_flanking_residues(residual: int, flanking: str) -> tuple:
    ''''''
    def split_flankers(residual, flanking) -> tuple:
        ''''''
        cterm = residual // 2
        nterm = residual - cterm
        return nterm, cterm
    
    residual = int(residual)
    if residual < 6 or flanking == "split":
        return split_flankers(residual, flanking)
    elif flanking == "nterm":
        return residual-3, 3
    elif flanking == "cterm":
        return 3, residual-3
    else:
        raise ValueError(f"Paramter <flanking> can only be 'split', 'nterm', or 'cterm'. flanking: {flanking}")

def adjust_flanking(rfdiffusion_pose_opts: str, flanking_type: str, total_flanker_length:int=None) -> str:
    '''AAA'''
    def get_contigs_str(rfdiff_opts: str) -> str:
        elem = [x for x in rfdiff_opts.split(" ") if x.startswith("'contigmap.contigs=")][0]
        contig_start = elem.find("[") +1
        contig_end = elem.find("]")
        return elem[contig_start:contig_end]
    
    # extract contig from contigs_str
    contig = get_contigs_str(rfdiffusion_pose_opts)
    
    # extract flankings and middle part
    csplit = contig.split("/")
    og_nterm, middle, og_cterm = int(csplit[0]), "/".join(csplit[1:-1]), int(csplit[-1])
    
    # readjust flankings according to flanking_type and max_pdb_length
    pdb_length = total_flanker_length or og_nterm+og_cterm
    nterm, cterm = divide_flanking_residues(pdb_length, flanking=flanking_type)
    
    # reassemble contig string and replace with hallucinate pose opts.
    reassembled = f"{nterm}/{middle}/{cterm}"
    return rfdiffusion_pose_opts.replace(contig, reassembled)

def update_and_copy_reference_frags(input_df: pd.DataFrame, ref_col:str, desc_col:str, motif_prefix: str, out_pdb_path=None, keep_ligand_chain:str="") -> list[str]:
    ''''''
    # create residue mappings {old: new} for renaming
    list_of_mappings = [utils.biopython_tools.residue_mapping_from_motif(ref_motif, inp_motif) for ref_motif, inp_motif in zip(input_df[f"{motif_prefix}_con_ref_pdb_idx"].to_list(), input_df[f"{motif_prefix}_con_hal_pdb_idx"].to_list())]

    # compile list of output filenames
    output_pdb_names_list = [f"{out_pdb_path}/{desc}.pdb" for desc in input_df[desc_col].to_list()]
    
    # renumber
    print(keep_ligand_chain)
    return [utils.biopython_tools.renumber_pdb_by_residue_mapping(ref_frag, res_mapping, out_pdb_path=pdb_output, keep_chain=keep_ligand_chain) for ref_frag, res_mapping, pdb_output in zip(input_df[ref_col].to_list(), list_of_mappings, output_pdb_names_list)]

def parse_outfilter_args(scoreterm_str: str, weights_str: str, df: pd.DataFrame, prefix:str=None) -> tuple[list]:
    ''''''
    def check_for_col_in_df(col: str, datf: pd.DataFrame) -> None:
        if col not in datf.columns: raise KeyError(f"Scoreterm {col} not found in poses_df. Available scoreterms: {','.join(datf.columns)}")
    scoreterms = scoreterm_str.split(",")
    if prefix: scoreterms = [prefix + "_" + x for x in scoreterms]
    weights = [float(x) for x in weights_str.split(",")]
    check = [check_for_col_in_df(scoreterm, df) for scoreterm in scoreterms]

    if not len(scoreterms) == len(weights): raise ValueError(f"Length of --output_scoreterms ({scoreterm_str}: {len(scoreterm_str)}) and --output_scoreterm_weights ({weights_str}: {len(weights_str)}) is not the same. Both arguments must be of the same length!")

    return scoreterms, weights

def extract_rosetta_pose_opts(input_data: pd.Series) -> str:
    '''AAA'''
    def collapse_dict_values(in_dict: dict) -> str:
        return ",".join([str(y) for x in in_dict.values() for y in list(x)])
    native_file = f"-in:file:native ref_fragments/{input_data['poses_description']}.pdb"
    script_vars = f"-parser:script_vars motif_res='{collapse_dict_values(input_data['motif_residues'])}' cat_res='{collapse_dict_values(input_data['fixed_residues'])}'"
    return [" ".join([native_file, script_vars])]

def write_rosetta_pose_opts_to_json(input_df: pd.DataFrame, path_to_json_file: str) -> str:
    '''AAA'''
    pose_opts_dict = {input_df.loc[index, "poses_description"]: extract_rosetta_pose_opts(input_df.loc[index]) for index in input_df.index}
    with open(path_to_json_file, 'w') as f:
        json.dump(pose_opts_dict, f)
    return path_to_json_file

def parse_diffusion_options(default_opts: str, additional_opts: str) -> str:
    '''AAA'''
    def_opts = [x for x in default_opts.split(" ") + additional_opts.split(" ") if x]
    def_opts_dict = {x.split("=")[0]: "=".join(x.split("=")[1:]) for x in def_opts}
    return " ".join([f"{k}={v}" for k, v in def_opts_dict.items()])

def check_for_params(path: str, ligand_chain: str):
    '''Checks if params-file is present in output of run_ensemble_evaluator.py //
        If no params file could be generated, then we also do not want Rosetta to use the ligand information.
    
        TODO: Implement flag -extra_res_fa if params file is found to make sure that the ligand is properly loaded.
    '''
    if os.path.isfile(f"{path}/ligand/LG1.params"): return ligand_chain
    else: return None

def calc_ligand_stats(input_df: pd.DataFrame, ref_frags_col:str, ref_motif_col:str, poses_motif_col:str, prefix:str, ligand_chain:str="Z") -> None:
    '''
    Superimposes the poses onto reference fragments in input_df[ref_frags_col] by specified motifs in input_df. Then calculates statistics over ligands. (if it is clashing and the number of contacts).
    '''
    # superimpose reference frags onto poses to make sure ligand calculation works in the same coordinate frame:
    poses = [superimposition_tools.superimpose_pdb_by_motif(ref_frag, pose, fixed_motif=ref_motif, mobile_motif=pose_motif, atoms=["CA"]) for pose, ref_frag, pose_motif, ref_motif in zip(input_df["poses"].to_list(), input_df[ref_frags_col].to_list(), input_df[poses_motif_col].to_list(), input_df[ref_motif_col].to_list())]

    # calculate statistics of ligands:
    input_df[f"{prefix}_ligand_clash"] = [utils.metrics.check_for_ligand_clash_of_pdb(pose, ligand_chain=ligand_chain, ligand_pdb_path=ref_pose, dist=1.8, ignore_atoms=["H"]) for pose, ref_pose in zip(input_df["poses"].to_list(), input_df[ref_frags_col].to_list())]
    input_df[f"{prefix}_peratom_ligand_contacts"] = [utils.metrics.calc_ligand_contacts_of_pdb(pose, ligand_chain=ligand_chain, ligand_pdb_path=ref_pose, d_0=3.5, r_0=3.5, ignore_atoms=["H"]) for pose, ref_pose in zip(input_df["poses"].to_list(), input_df[ref_frags_col].to_list())]

    return input_df

def overwrite_linker_length(pose_opts: str, total_length:int, max_linker_length:int=100) -> str:
    '''overwrites linker length and allows linkers to be of any length (with at least the provided linker length)'''
    # extract contig string from pose_opts
    full_contig_str = [x for x in pose_opts.split(" ") if x.startswith("'contigmap.contigs")][0]
    contig_str = full_contig_str[full_contig_str.find("[")+1:full_contig_str.find("]")]
    contigs = [x for x in contig_str.split("/") if x][1:-1]
    
    # replace fixed linkers in contigs string with linker ranges
    new_contigs = "/".join([x if x[0].isalpha() else f"{x}-{str(max_linker_length)}" for x in contigs])
    new_contig_str = full_contig_str.replace("/".join(contigs), new_contigs)

    # return replaced contig pose-opts:
    return pose_opts.replace(full_contig_str, f"{new_contig_str} contigmap.length={str(total_length)}-{str(total_length)} ")

def main(args):
    # print Status
    print(f"\n{'#'*50}\nRunning rfdiffusion_ensembles_sampling.py on {args.input_dir}\n{'#'*50}\n")

    # Parse Poses
    pdb_dir = f"{args.input_dir}/pdb_in/"
    ensembles = Poses(args.output_dir, glob(f"{pdb_dir}/*.pdb"))
    ensembles.max_rfdiffusion_gpus = args.max_rfdiffusion_gpus
    plotdir = f"{ensembles.dir}/plots"
    plot_dir = ensembles.plot_dir
    keep_ligand_chain = check_for_params(args.input_dir, args.ligand_chain)

    # Read scores of selected paths from ensemble_evaluator and store them in poses_df:
    path_df = pd.read_json(f"{args.input_dir}/selected_paths.json").reset_index().rename(columns={"index": "rdescription"})
    ensembles.poses_df = ensembles.poses_df.merge(path_df, left_on="poses_description", right_on="rdescription")
    ensembles.max_rosetta_cpus = 500
    ensembles.max_mpnn_gpus = 10

    # change cterm and nterm flankers according to input args.
    if args.flanking: ensembles.poses_df["rfdiffusion_pose_opts"] = [adjust_flanking(rfdiffusion_pose_opts_str, args.flanking, args.total_flanker_length) for rfdiffusion_pose_opts_str in ensembles.poses_df["rfdiffusion_pose_opts"].to_list()]
    elif args.total_flanker_length:
        raise ValueError(f"Argument 'total_flanker_length' was given, but not 'flanking'! Both args have to be provided.")
    
    # adjust linkers if overwrite_linker_lengths option was set:
    if args.overwrite_linker_lengths:
        linker_length, total_length = [int(x) for x in args.overwrite_linker_lengths.split(",")]
        ensembles.poses_df["rfdiffusion_pose_opts"] = [overwrite_linker_length(pose_opts, total_length, linker_length) for pose_opts in ensembles.poses_df["rfdiffusion_pose_opts"].to_list()]

    # Check if merger was successful:
    if len(ensembles.poses_df) == len(ensembles.poses): print(f"Loading of Pose contigs into poses_df successful. Continuing to hallucination.")
    else: raise ValueError(f"Merging of diffusion_opts into poses_df failed! Check if keys in hallucination_opts match with pose_names!!!")

    # store original motifs for calculation of Motif RMSDs later
    motif_cols = ["fixed_residues", "motif_residues"]
    ensembles.poses_df["template_motif"] = ensembles.poses_df["motif_residues"]
    ensembles.poses_df["template_fixedres"] = ensembles.poses_df["fixed_residues"]

    # RFdiffusion:
    diffusion_options = f"diffuser.T={str(args.rfdiffusion_timesteps)} potentials.guide_scale={args.rfdiff_guide_scale} inference.num_designs={args.num_rfdiffusions} potentials.guiding_potentials=[\\'type:monomer_ROG_new,weight:{args.ROG_weight}\\',\\'type:substrate_centroid,weight:7\\',\\'type:substrate_contacts,weight:4\\'] potentials.guide_decay='quadratic'"
    diffusion_options = parse_diffusion_options(diffusion_options, args.rfdiffusion_additional_options)
    diffusions = ensembles.rfdiffusion(options=diffusion_options, pose_options=list(ensembles.poses_df["rfdiffusion_pose_opts"]), prefix="rfdiffusion", max_gpus=args.max_rfdiffusion_gpus)

    # Update motif_res and fixedres to residue mapping after rfdiffusion 
    _ = [ensembles.update_motif_res_mapping(motif_col=col, inpaint_prefix="rfdiffusion") for col in motif_cols]
    _ = ensembles.update_res_identities(identity_col="catres_identities", inpaint_prefix="rfdiffusion")

    # calculate ROG and contacts:
    ensembles.poses_df["rfdiffusion_rog"] = [metrics.calc_rog_of_pdb(pose) for pose in ensembles.poses_df["poses"].to_list()]
    ensembles.poses_df["rfdiffusion_contacts_short"] = [metrics.calc_intra_contacts_of_pdb(pose) for pose in ensembles.poses_df["poses"].to_list()]
    ensembles.poses_df["rfdiffusion_contacts_long"] = [metrics.calc_intra_contacts_of_pdb(pose, d_0=3.9, r_0=3.9) for pose in ensembles.poses_df["poses"].to_list()]

    # Calculate RMSD and composite score:
    diffusion_template_rmsd = ensembles.calc_motif_bb_rmsd_dir(ref_pdb_dir=pdb_dir, ref_motif=list(ensembles.poses_df["template_motif"]), target_motif=list(ensembles.poses_df["motif_residues"]), metric_prefix="rfdiffusion_template_bb_ca", remove_layers=1)
    diffusion_comp_score = ensembles.calc_composite_score("rfdiffusion_comp_score", ["rfdiffusion_plddt", "rfdiffusion_template_bb_ca_motif_rmsd"], [-1, args.rfdiffusion_rmsd_weight])

    # Copy and rewrite Fragments into output_dir/reference_fragments
    if not os.path.isdir((updated_ref_frags_dir := f"{ensembles.dir}/updated_reference_frags/")): os.makedirs(updated_ref_frags_dir)
    
    ensembles.poses_df["updated_reference_frags_location"] = update_and_copy_reference_frags(ensembles.poses_df, ref_col="input_poses", desc_col="poses_description", motif_prefix="rfdiffusion", out_pdb_path=updated_ref_frags_dir, keep_ligand_chain=keep_ligand_chain)
    
    # superimpose poses on reference frags and calculate ligand scores:
    if keep_ligand_chain: calc_ligand_stats(input_df=ensembles.poses_df, ref_frags_col="updated_reference_frags_location", ref_motif_col="motif_residues", poses_motif_col="motif_residues", prefix="rfdiffusion", ligand_chain=args.ligand_chain)

    # remove clashing structures:
    ensembles.poses_df = ensembles.poses_df[ensembles.poses_df["rfdiffusion_ligand_clash"] == False]

    # filter based on rfdiffusion pLDDT (implement args.rfdiffusion_plddt_fraction):
    rfdiff_plddt_filter = ensembles.filter_poses_by_score(0.8, "rfdiffusion_plddt", prefix="rfdiffusion_plddt_filter", ascending=False, plot=["rfdiffusion_plddt", "rfdiffusion_template_bb_ca_motif_rmsd", "rfdiffusion_peratom_ligand_contacts"])

    # filter based on ligand_contacts:
    rfdiff_contacts_filter = ensembles.filter_poses_by_score(0.3, "rfdiffusion_peratom_ligand_contacts", prefix="rfdiffusion_ligand_contacts_filter", plot=["rfdiffusion_plddt", "rfdiffusion_template_bb_ca_motif_rmsd", "rfdiffusion_peratom_ligand_contacts"])
    
    # cycle MPNN and FastRelax:
    index_layers=1
    pdb_loc_col = "rfdiffusion_location"
    fr_mpnn_rmsd_traj = PlottingTrajectory(y_label="RMSD [\u00C5]", location=f"{plot_dir}/fr_mpnn_rmsd_trajectory.png", title="Motif BB-Ca\nTrajectory", dims=(0,3))
    for i in range(3):
        cycle_prefix = f"cycle_{str(i)}"

        # run mpnn and fr
        ensembles, index_layers, fr_pdb_dir = mpnn_fr(ensembles, prefix=f"cycle_{str(i)}", index_layers_to_reference=index_layers, fastrelax_pose_opts="fr_pose_opts", pdb_location_col=pdb_loc_col, ref_pdb_dir=pdb_dir, reference_location_col="updated_reference_frags_location")

        # plot
        fr_mpnn_rmsd_traj.add_and_plot(ensembles.poses_df[f"cycle_{str(i)}_fr_bb_ca_motif_rmsd"], f"cycle_{str(i)}")

        # setup next cycle
        pdb_loc_col = f"cycle_{str(i)}_fr_location"

    # superimpose poses on reference frags and calculate ligand scores:
    if keep_ligand_chain: calc_ligand_stats(input_df=ensembles.poses_df, ref_frags_col="updated_reference_frags_location", ref_motif_col="motif_residues", poses_motif_col="motif_residues", prefix="pre_esm", ligand_chain=args.ligand_chain)

    # remove clashing poses:
    ensembles.poses_df = ensembles.poses_df[ensembles.poses_df["pre_esm_ligand_clash"] == False]

    # filter down by total_score to max_esm_inputs:
    total_score_filter = ensembles.filter_poses_by_score(args.num_mpnn_inputs, f"{cycle_prefix}_fr_total_score", prefix=f"pre_mpnn_filter", plot=["pre_esm_peratom_ligand_contacts", f"{cycle_prefix}_fr_total_score"])

    # run mpnn and predict with ESMFold:
    ensembles, index_layers = mpnn_design_and_esmfold(ensembles, prefix="round1", index_layers_to_reference=index_layers, num_mpnn_seqs=args.num_mpnn_seqs, num_esm_inputs=args.num_esm_inputs, num_esm_outputs_per_input_backbone=args.num_esm_outputs_per_input_backbone, bb_rmsd_dir=fr_pdb_dir, ref_pdb_dir=pdb_dir)

    # superimpose poses on reference frags and calculate ligand scores:
    if keep_ligand_chain: calc_ligand_stats(input_df=ensembles.poses_df, ref_frags_col="updated_reference_frags_location", ref_motif_col="motif_residues", poses_motif_col="motif_residues", prefix="post_esm", ligand_chain=args.ligand_chain)

    # Filter down to final set of .pdbs that will be input for Rosetta Refinement:
    #scoreterms, weights = parse_outfilter_args(args.output_scoreterms, args.output_scoreterm_weights, ensembles.poses_df, prefix="round1")
    out_filterscore = ensembles.calc_composite_score("out_filter_comp_score", (st := [f"round1_esm_plddt", f"round1_esm_bb_ca_rmsd", f"round1_esm_bb_ca_motif_rmsd"]), [-0.5,0.5,1])
    out_filter = ensembles.filter_poses_by_score(args.num_refinement_inputs, f"out_filter_comp_score", prefix="out_filter", plot=st)
    results_dir = f"{args.output_dir}/intermediate_results/"
    ref_frag_dir = f"{results_dir}/ref_fragments/"
    if not os.path.isdir(ref_frag_dir): os.makedirs(ref_frag_dir, exist_ok=True)
    ensembles.dump_poses(results_dir)

    # Copy and rewrite Fragments into output_dir/reference_fragments
    updated_ref_pdbs = update_and_copy_reference_frags(ensembles.poses_df, ref_col="input_poses", desc_col="poses_description", motif_prefix="rfdiffusion", out_pdb_path=ref_frag_dir, keep_ligand_chain=args.ligand_chain)

    # Write PyMol Alignment Script
    ref_originals = [shutil.copy(ref_pose, f"{results_dir}/") for ref_pose in ensembles.poses_df["input_poses"].to_list()]
    pymol_script = utils.pymol_tools.write_pymol_alignment_script(ensembles.poses_df, scoreterm="out_filter_comp_score", top_n=args.num_refinement_inputs, path_to_script=f"{results_dir}/align.pml")

    # write Rosetta Pose Options to a .json file:
    ros_pose_opts = write_rosetta_pose_opts_to_json(ensembles.poses_df, path_to_json_file=f"{results_dir}/rosetta_pose_opts.json")
    dumped = ensembles.dump_poses(f"{results_dir}/pdb_in/")
    out_df = ensembles.poses_df[["poses_description", "fixed_residues", "motif_residues"]].set_index("poses_description")
    out_df.to_json(f"{results_dir}/motif_res.json")

    ### REFINEMENT ###
    # initial number of refinement runs is higher:
    fr_n = 25

    # instantiate plotting trajectories:
    esm_plddt_traj = PlottingTrajectory(y_label="ESMFold pLDDT", location=f"{plot_dir}/esm_plddt_trajectory.png", title="ESMFold Trajectory", dims=(0,100))
    esm_bb_ca_rmsd_traj = PlottingTrajectory(y_label="RMSD [\u00C5]", location=f"{plot_dir}/esm_bb_ca_trajectory.png", title="ESMFold BB-Ca\nRMSD Trajectory", dims=(0,10))
    esm_motif_ca_rmsd_traj = PlottingTrajectory(y_label="RMSD [\u00C5]", location=f"{plot_dir}/esm_motif_ca_trajectory.png", title="ESMFold Motif-Ca\nRMSD Trajectory", dims=(0,8))
    esm_catres_rmsd_traj = PlottingTrajectory(y_label="RMSD [\u00C5]", location=f"{plot_dir}/esm_catres_rmsd_trajectory.png", title="ESMFold Motif\nSidechain RMSD Trajectory", dims=(0,8))
    refinement_total_score_traj = PlottingTrajectory(y_label="Rosetta total score [REU]", location=f"{plot_dir}/rosetta_total_score_trajectory.png", title="FastDesign Total Score Trajectory")
    refinement_motif_ca_rmsd_traj = PlottingTrajectory(y_label="RMSD [\u00C5]", location=f"{plot_dir}/refinement_motif_rmsd_trajectory.png", title="Refinement Motif\nBB-Ca RMSD Trajectory", dims=(0,8))

    # cycle fastrelax, proteinmpnn and ESMFold
    filter_layers = 2
    index_layers_to_remove = 2
    idx = index_layers
    for i in range(args.refinement_cycles):
        # refine
        ensembles.poses_df["refinement_opts"] = ensembles.poses_df["fr_pose_opts"].str.replace(" -parser:script_vars ", f" -parser:script_vars sd={str(0.5 + i)} ")
        ensembles, index_layers_n = fr_mpnn_esmfold(ensembles, prefix=(c_pref := f"refinement_cycle_{str(i).zfill(2)}"), n=fr_n, index_layers_to_reference=index_layers, fastrelax_pose_opts="refinement_opts", ref_pdb_dir=pdb_dir)
        
        # plot
        esm_plddt_traj.add_and_plot(ensembles.poses_df[f"{c_pref}_esm_plddt"], c_pref)
        esm_bb_ca_rmsd_traj.add_and_plot(ensembles.poses_df[f"{c_pref}_esm_bb_ca_rmsd"], c_pref)
        esm_motif_ca_rmsd_traj.add_and_plot(ensembles.poses_df[f"{c_pref}_esm_bb_ca_motif_rmsd"], c_pref)
        esm_catres_rmsd_traj.add_and_plot(ensembles.poses_df[f"{c_pref}_esm_catres_motif_heavy_rmsd"], c_pref)
        refinement_total_score_traj.add_and_plot(ensembles.poses_df[f"{c_pref}_refinement_total_score"], c_pref)
        refinement_motif_ca_rmsd_traj.add_and_plot(ensembles.poses_df[f"{c_pref}_refinement_bb_ca_motif_rmsd"], c_pref)

        #filter
        cycle_filter = ensembles.filter_poses_by_score(5, f"{c_pref}_esm_comp_score", prefix=f"{c_pref}_final_filter", remove_layers=filter_layers, plot=[f"{c_pref}_esm_comp_score", f"{c_pref}_esm_plddt", f"{c_pref}_esm_bb_ca_rmsd", f"{c_pref}_esm_bb_ca_motif_rmsd", f"{c_pref}_esm_catres_motif_heavy_rmsd"])
        
        # reindex poses
        index_removed = ensembles.reindex_poses(out_dir=f"{c_pref}_reindexed_poses", remove_layers=index_layers_to_remove)
        fr_n = 5
        filter_layers = 3
        index_layers_to_remove = 3
        index_layers = idx+1

    # superimpose poses on reference frags and calculate ligand scores:
    if keep_ligand_chain: calc_ligand_stats(input_df=ensembles.poses_df, ref_frags_col="updated_reference_frags_location", ref_motif_col="motif_residues", poses_motif_col="motif_residues", prefix="post_refinement", ligand_chain=args.ligand_chain)

    # make new results, copy fragments and write alignment_script
    results_dir = f"{args.output_dir}/results/"
    ref_frag_dir = f"{results_dir}/ref_fragments/"
    if not os.path.isdir(ref_frag_dir): os.makedirs(ref_frag_dir, exist_ok=True)
    ensembles.dump_poses(results_dir)

    # Copy and rewrite Fragments into output_dir/reference_fragments
    updated_ref_pdbs = update_and_copy_reference_frags(ensembles.poses_df, ref_col="input_poses", desc_col="poses_description", motif_prefix="rfdiffusion", out_pdb_path=ref_frag_dir, keep_ligand_chain=args.ligand_chain)

    # Write PyMol Alignment Script
    ref_originals = [shutil.copy(ref_pose, f"{results_dir}/") for ref_pose in ensembles.poses_df["input_poses"].to_list()]
    pymol_script = utils.pymol_tools.write_pymol_alignment_script(ensembles.poses_df, scoreterm=f"{c_pref}_esm_comp_score", top_n=args.num_outputs, path_to_script=f"{results_dir}/align.pml")

    print("done")


if __name__ == "__main__":
    import argparse

    argparser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    argparser.add_argument("--input_dir", type=str, required=True, help="input_directory that contains all ensemble *.pdb files to be hallucinated (max 1000 files).")
    argparser.add_argument("--output_dir", type=str, required=True, help="output_directory")
    argparser.add_argument("--fastrelax_protocol", type=str, default="/home/mabr3112/riff_diff/rosetta/fastrelax_constrained.xml", help="Protocol of fastrelax-MPNN cycles")
    argparser.add_argument("--refinement_protocol", type=str, default="/home/mabr3112/riff_diff/rosetta/fr_refine.xml")
    argparser.add_argument("--refinement_cycles", type=int, default=5, help="Number of Fastrelax-mpnn-esmfold refinement cycles to run.")

    # rfdiffusion options
    argparser.add_argument("--num_rfdiffusions", type=int, default=15, help="Number of rfdiffusion trajectories.")
    argparser.add_argument("--rfdiffusion_timesteps", type=int, default=50, help="Number of RFdiffusion timesteps to diffuse.")
    argparser.add_argument("--rfdiffusion_rmsd_weight", type=float, default=3, help="Weight of hallucination RMSD score for filtering sampled hallucination")
    argparser.add_argument("--max_rfdiffusion_gpus", type=int, default=15, help="On how many GPUs at a time to you want to run Hallucination?")
    argparser.add_argument("--rfdiffusion_additional_options", type=str, default="", help="Any additional options that you want to parse to RFdiffusion.")
    argparser.add_argument("--num_rfdiffusion_outputs_per_input_backbone", type=int, default=15, help="Number of rfdiffusions that should be kept per input fragment.")
    argparser.add_argument("--rfdiff_guide_scale", type=int, default=5, help="Guide_scale value for RFDiffusion")
    argparser.add_argument("--ROG_weight", type=int, default=5, help="Weight of monomer_ROG potential. Important for small porteins")

    # linkers
    argparser.add_argument("--flanking", type=str, default=None, help="Overwrites contig output of 'run_ensemble_evaluator.py'. Can be either 'split', 'nterm', 'cterm'")
    argparser.add_argument("--total_flanker_length", type=int, default=None, help="Overwrites contig output of 'run_ensemble_evaluator.py'. Set the max length of the pdb-file that is being hallucinated. Will only be used in combination with 'flanking'")
    argparser.add_argument("--overwrite_linker_lengths", type=str, default='200,50', help="specify first total length of the protein, then maximum length that should be assigned to the linkers.\nExample: --overwrite_linekr_lengths='200,75' -> would set the maximum length of the protein to 200 and would overwrite the linkers to ranges between ~5-75.")

    # mpnn options
    argparser.add_argument("--num_mpnn_inputs", type=int, default=200, help="Number of input backbones to ProteinMPNN before predicting them with ESMFold")
    argparser.add_argument("--num_mpnn_seqs", type=int, default=80, help="Number of MPNN Sequences to generate for each input backbone.")
    argparser.add_argument("--num_esm_inputs", type=int, default=30, help="Number of MPNN Sequences for each input backbone that should be predicted. Typically quarter to half of the sequences generated by MPNN is a good value.")
    argparser.add_argument("--num_esm_outputs_per_input_backbone", type=int, default=1, help="Number of ESM Outputs for each backbone that is inputted to ESMFold.")

    # output options
    argparser.add_argument("--num_refinement_inputs", type=int, default=10, help="Number of .pdb files that will be stored into the final output directory.")
    argparser.add_argument("--output_scoreterms", type=str, default="esm_plddt,esm_bb_ca_motif_rmsd", help="Scoreterms to use to filter ESMFolded PDBs to the final output pdbs. IMPORTANT: if you supply scoreterms, also supply weights and always check the filter output plots in the plots/ directory!")
    argparser.add_argument("--output_scoreterm_weights", type=str, default="-1,1.5", help="Weights for how to combine the scoreterms listed in '--output_scoreterms'")
    argparser.add_argument("--ligand_chain", type=str, default="Z", help="Chain name of your ligand chain.")
    argparser.add_argument("--num_outputs", type=int, default=50, help="Number of .pdb-files you would like to have as output.")
    args = argparser.parse_args()

    main(args)