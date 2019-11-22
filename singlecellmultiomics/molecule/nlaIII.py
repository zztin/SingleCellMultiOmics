from singlecellmultiomics.molecule.molecule import Molecule
from singlecellmultiomics.molecule.featureannotatedmolecule import FeatureAnnotatedMolecule


class NlaIIIMolecule(Molecule):
    """Nla III based Molecule class

    Args:
        fragments (singlecellmultiomics.fragment.Fragment): Fragments to associate to the molecule

        **kwargs: extra args

    """

    def __init__(self, fragment,
                 site_has_to_be_mapped=False,
                 # molecule is invalid when NLA site does not map  (requires
                 # reference)
                 **kwargs):
        self.site_has_to_be_mapped = site_has_to_be_mapped
        Molecule.__init__(self, fragment, **kwargs)

    def write_tags(self):
        Molecule.write_tags(self)
        if self.reference is not None:  # Only calculate this statistic when a reference is available
            if self.get_cut_site() is not None:
                self.set_meta('Us', self.get_undigested_site_count())

    def is_valid(self, set_rejection_reasons=False, reference=None):

        try:
            chrom, start, strand = self.get_cut_site()
        except Exception as e:
            if set_rejection_reasons:
                self.set_rejection_reason('no_cut_site_found')
            return False

        if self.site_has_to_be_mapped:

            if reference is None:
                if self.reference is None:
                    raise ValueError(
                        'Please supply a reference (PySAM.FastaFile)')
            reference = self.reference

            if reference.fetch(chrom, start, start + 4).upper() != 'CATG':
                if set_rejection_reasons:
                    self.set_rejection_reason('no_CATG_in_ref')
                return False

        return True

    def get_fragment_span_sequence(self, reference=None):
        """Obtain the sequence between the start and end of the molecule
        Args:
            reference(pysam.FastaFile) : reference  to use.
                If not specified self.reference is used
        Returns:
            sequence (str)
        """
        if reference is None:
            if self.reference is None:
                raise ValueError('Please supply a reference (PySAM.FastaFile)')
        reference = self.reference
        return reference.fetch(
            self.chromosome,
            self.spanStart,
            self.spanEnd).upper()

    def get_undigested_site_count(self, reference=None):
        """
        Obtain the amount of undigested sites in the span of the molecule

        Parameters
        ----------
        reference : pysam.FastaFile or similiar

        Returns
        -------
        undigested_site_count : int
            amount of undigested cut sites in the mapping span of the molecule

        Raises:
        -------
        ValueError : when the span of the molecule is not properly defined
        """
        if reference is None:
            if self.reference is None:
                raise ValueError('Please supply a reference (PySAM.FastaFile)')
        reference = self.reference

        seq = self.get_fragment_span_sequence(reference)
        total = seq.count('CATG')
        if self.strand == 0 and seq.endswith('CATG'):
            total -= 1
        elif self.strand == 1 and seq.startswith('CATG'):
            total -= 1
        return total


class AnnotatedNLAIIIMolecule(FeatureAnnotatedMolecule, NlaIIIMolecule):
    """Nla III based Molecule which is annotated with features (genes/exons/introns, .. )

    Args:
        fragments (singlecellmultiomics.fragment.Fragment): Fragments to associate to the molecule
        features (singlecellmultiomics.features.FeatureContainer) : container to use to obtain features from
        **kwargs: extra args

    """

    def write_tags(self):
        NlaIIIMolecule.write_tags(self)
        FeatureAnnotatedMolecule.write_tags(self)

    def __init__(self, fragment, features, **kwargs):
        FeatureAnnotatedMolecule.__init__(self, fragment, features, **kwargs)
        NlaIIIMolecule.__init__(self, fragment, **kwargs)
