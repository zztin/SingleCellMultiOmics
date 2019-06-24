#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from .statistic import StatisticHistogram
import singlecellmultiomics.pyutils as pyutils
import collections
import pandas as pd

import matplotlib
matplotlib.rcParams['figure.dpi'] = 160
matplotlib.use('Agg')
import matplotlib.pyplot as plt

class TagHistogram(StatisticHistogram):
    def __init__(self,args):
        StatisticHistogram.__init__(self, args)
        self.histogram = collections.Counter()

    def processRead(self,read):
        if read.has_tag('EX'):
            if read.get_tag('EX')=='Unassigned_NoFeatures':
                self.histogram["Not assigned to exon"]+=1
            elif read.get_tag('EX')=='Assigned':
                self.histogram["Assigned to exon"]+=1
            else:
                self.histogram["Unkown exon assignment"]+=1

        if read.has_tag('XS'):
            if read.get_tag('XS')=='Unassigned_NoFeatures':
                self.histogram["Not assigned to gene/intron"]+=1
            elif read.get_tag('XS')=='Assigned':
                self.histogram["Assigned to gene/intron"]+=1
            else:
                self.histogram["Unkown gene/intron assignment"]+=1

        if read.has_tag('Is'):
            self.histogram[f"Sequencer_{read.get_tag('Is')}"]+=1

        if read.has_tag('LY'):
            self.histogram[f"Library_{read.get_tag('LY')}"]+=1


    def __repr__(self):
        rt = 'Tag obs::'
        for reason, obs in self.histogram.most_common():
            rt += f'{reason}\t:\t{obs}\n'
        return rt
    def __iter__(self):
        return iter(self.histogram.most_common())

    def plot(self, target_path, title=None):
        df = pd.DataFrame.from_dict({'Tag':dict(self)}).T

        df.plot.bar(figsize=(10,4)).legend(bbox_to_anchor=(1, 0.98))
        if title is not None:
            plt.title(title)

        plt.tight_layout()
        plt.subplots_adjust(right=0.6)
        plt.savefig(target_path)

        ax = plt.gca()
        ax.set_yscale('log')
        plt.savefig(target_path.replace('.png','.log.png'))
        plt.close()