#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from singlecellmultiomics.bamProcessing.bamBinCounts import blacklisted_binning_contigs
from singlecellmultiomics.bamProcessing import sorted_bam_file
import pysam
import os
from shutil import move
from multiprocessing import Pool
from singlecellmultiomics.fragment import CHICFragment
from singlecellmultiomics.molecule import CHICMolecule, MoleculeIterator
from more_itertools import chunked
import shutil
import singlecellmultiomics
from singlecellmultiomics.bamProcessing.bamFunctions import sorted_bam_file, get_reference_from_pysam_alignmentFile, write_program_tag, MapabilityReader, verify_and_fix_bam
import argparse
import uuid
import colorama
from datetime import datetime
import traceback
import colorama
from datetime import datetime


argparser = argparse.ArgumentParser(
    formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    description='Assign molecules, set sample tags, set alleles')
argparser.add_argument('bamin', type=str)
argparser.add_argument(
    '-temp',
    type=str,
    default='bamtagmultiome_temp',
    help="Temp folder")

argparser.add_argument('-o', type=str, help="output bam file", required=True)
argparser.add_argument('-job_bin_size', type=int, default=5_000_000, help='How large are the job bins in bp')
argparser.add_argument('-timeout', type=int, default=60*15, help='How long do we try to resolve a bin (seconds)')
argparser.add_argument('-min_mapping_qual', type=int, default=40, help='Mapping quality pre-filter. All reads with a lower mapping quality are discarded immediately ')
argparser.add_argument('-fragment_length', type=int, default=500, help='Maximum fragment length')
argparser.add_argument('-chunksize', type=int, default=300, help='Amount of bins per chunk')
argparser.add_argument('-job_chunk_size', type=int, default=50, help='Amount of segments per job')

argparser.add_argument('-blacklist', type=str, help='blacklist (bed file), with contig start end')
argparser.add_argument('-debug_job_bin_bed', type=str, help='Path to write a bed file')


def run_multiome_tagging_cmd(commandline):
    args = argparser.parse_args(commandline)
    run_multiome_tagging(args)

def merge_bams( bams, output_path ):
    if len(bams)==1:
        move(bams[0], output_path)
        move(bams[0]+'.bai', output_path+'.bai')
    else:
        pysam.merge(output_path, *bams, '-@ 4 -f -l 1 -c')
        pysam.index(output_path, '-@ 4')
        for o in bams:
            os.remove(o)
            os.remove(o+'.bai')
    return output_path


def run_tagging(args):

    (alignments_path, temp_dir, timeout_time), arglist = args

    i = 0
    tid = 0
    contig = 'None'

    kill = False # kill signal

    def timeout_check_function(iteration, mol_iter, reads ):
        nonlocal time_start
        nonlocal timeout_time
        if (datetime.now()-time_start).total_seconds() > timeout_time:
            kill=True
            raise TimeoutError()

    target_file = f"{temp_dir}/{uuid.uuid4()}.bam"


    timeouts = 0
    total_molecules = 0
    with pysam.AlignmentFile(alignments_path) as alignments:

        with sorted_bam_file(target_file, origin_bam=alignments, mode='wbu',fast_compression=True) as output:

            for contig, start, end, fetch_start,fetch_end, molecule_class, fragment_class, molecule_iterator_args, \
                        fragment_class_args, molecule_class_args in arglist:
                molecule_iterator_args['progress_callback_function'] = timeout_check_function
                time_start = datetime.now()
                try:
                    #print(fetch_start, fetch_end)
                    for i,molecule in enumerate(
                            MoleculeIterator(alignments, molecule_class, fragment_class, contig=contig, start=fetch_start, end=fetch_end,
                                            **molecule_iterator_args, molecule_class_args=molecule_class_args,fragment_class_args=fragment_class_args
                                            )
                        ):

                        cut_site_contig, cut_site_pos = molecule[0].get_site_location()

                        if cut_site_pos>=fetch_end:
                            #print('Forcing exit')
                            break

                        if cut_site_contig!=contig or cut_site_pos<start or cut_site_pos>=end: # End is exclusive
                            continue

                        total_molecules+=1
                        molecule.write_tags()
                        molecule.write_pysam(output)

                except TimeoutError:
                    # Clean up?
                    timeouts+=1
                    pass

    if total_molecules>0:
        return target_file, (tid, contig, start,end, len(arglist), 'ok')
    else:
        # Clean up ?
        try:
            os.remove(target_file)
            os.remove(f'{target_file}.bai')
        except Exception as e:
                pass

        return None, (tid, contig, start,end, len(arglist), 'empty')




def run_multiome_tagging(args):

    alignments_path = args.bamin
    out_name = args.o
    temp_dir = args.temp
    fragment_size = args.fragment_length


    blacklist_generated_path = 'blacklist.bed'
    blacklist_generated_path = open(blacklist_generated_path,'w')


    for remove_existing_path in [args.o, f'{args.o}.bai']:
        if os.path.exists(remove_existing_path):
            print(f"Removing existing file {remove_existing_path}")
            os.remove(remove_existing_path)

    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)

    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)


    molecule_iterator_args = {
        'yield_overflow' : False,
        'yield_invalid' : False,
        'min_mapping_qual':args.min_mapping_qual
    }

    molecule_class_args = {

        'max_associated_fragments':1

    }

    fragment_class_args = { 'umi_hamming_distance':1 }

    time_start = datetime.now()

    failed_bins = set()

    total_commands=0


    def register_status(contig,start,end,status):
        if status=='timeout':
            failed_bins.add( (contig, start, end ) )
            blacklist_generated_path.write(f'{contig}\t{start}\t{end}\n')


    def cli_update(iteration, contig, start, end, status):
        if status=='timeout':
            print('\n'+colorama.Style.BRIGHT + colorama.Fore.RED + f"The bin {contig}:{start}-{end} timed out and will not be tagged " + colorama.Style.RESET_ALL)

        if total_commands>0:
            print(f'time:{(datetime.now()-time_start)}, completion: { ((iteration/total_commands)*100):.2f} % , {contig}:{start}-{end} {status}             ', end='\r')

    def filter_func( args ):

        iteration, (target,(tid, contig, start, end, wrote_jobs, status)) = args
        # Register:
        register_status(contig, start, end, status)
        cli_update(iteration, contig, start, end, status)
        # Force update:
        #force_update( iteration, tid=contig, bin_start=start, bin_end=end, status=status )

        # Dont process chunks where no molecules were generated
        return target is not None


    def get_commands(alignments_path,fragment_size, temp_dir,
                                     molecule_class, fragment_class,
                                     molecule_iterator_args,
                                     fragment_class_args,
                                     molecule_class_args,timeout_time, bin_size ,blacklist_path):
        yield from  (

             (contig, start, end, fetch_start,fetch_end,
                 molecule_class, fragment_class,
                 molecule_iterator_args,
                 fragment_class_args,
                 molecule_class_args,
                 )

              for contig,start,end,fetch_start,fetch_end in
                blacklisted_binning_contigs(
                        contig_length_resource = alignments,
                        bin_size = bin_size,
                        fragment_size=fragment_size,
                        blacklist_path=blacklist_path
                         ) #
        )


    # Dry run:
    total_commands = 0
    if args.debug_job_bin_bed:
        jbo = open(args.debug_job_bin_bed,'w')
    else:
        jbo = None

    with pysam.AlignmentFile(alignments_path) as alignments:
        for cmd in get_commands(alignments_path, fragment_size, temp_dir,
                CHICMolecule, CHICFragment,
                 molecule_iterator_args,
                 fragment_class_args,
                 molecule_class_args, args.timeout, args.job_bin_size, args.blacklist):
                total_commands+=1
                if jbo is not None:
                    jbo.write(f'{cmd[1]}\t{cmd[2]}\t{cmd[3]}\n')

    total_commands = int(total_commands/args.job_chunk_size)+1
    if jbo is not None:
        jbo.close()

    with Pool() as workers, pysam.AlignmentFile(alignments_path) as alignments:

        intermediate_bams = [
                merge_bams(bam_paths, f'{temp_dir}/chunk{i}.bam')
                for i,bam_paths in enumerate(chunked(
                    (qq[1][0] for qq in #(just extracts target from (iteration, (target,(contig, start, end, status))))
                    filter(
                        filter_func,
                        enumerate(workers.imap_unordered(
                            run_tagging,
                            # Commands for scCHiC:
                            ( ((alignments_path,temp_dir,args.timeout),command_list)
                            for command_list in chunked(get_commands(alignments_path, fragment_size, temp_dir,
                                    CHICMolecule, CHICFragment,
                                     molecule_iterator_args,
                                     fragment_class_args,
                                     molecule_class_args, args.timeout, args.job_bin_size, args.blacklist), args.job_chunk_size)
                                     )

            )))), args.chunksize))
            ]


        print(f'\nJobs are completed, now merging the results into {out_name}')
        merge_bams( intermediate_bams, out_name )
        print(f'Indexing the final bam at {out_name}')
        pysam.index(out_name)

    print('All done' + ' '*99)
    print(f'Took: {datetime.now() - time_start}')

if __name__ == '__main__':
    args = argparser.parse_args()
    run_multiome_tagging(args)
