#!/usr/bin/python3
import os
import pymatgen
import seekpath
from pymatgen.core.periodic_table import get_el_sp
from sssp import pseudo_dict, ecutwfc_dict, ecutrho_dict
from xml.etree import ElementTree
import combo
import subprocess
import numpy


def load_data():
    with open("desc.dat", "r") as f:
        ndata = int(f.readline())
        filename0 = [""]*ndata
        descriptor0 = numpy.zeros((ndata, 3), numpy.float_)
        for idata in range(ndata):
            line = f.readline()
            filename0[idata] = line.split()[0]
            descriptor0[idata, 0] = float(line.split()[1])
            descriptor0[idata, 1] = float(line.split()[2])
            descriptor0[idata, 2] = 1.0 / descriptor0[idata, 0]

    return descriptor0, filename0


class Simulator:
    def __init__(self):
        _, self.filename = load_data()

    def __call__(self, action):

        structure = pymatgen.Structure.from_file(self.filename[action[0]])
        structure.remove_oxidation_states()
        frac_coord2 = numpy.array(structure.frac_coords)
        for ipos in range(len(frac_coord2)):
            for iaxis in range(3):
                coord3 = frac_coord2[ipos, iaxis] * 6.0
                if abs(round(coord3) - coord3) < 0.001:
                    frac_coord2[ipos, iaxis] = float(round(coord3)) / 6.0
        #
        skp = seekpath.get_path((structure.lattice.matrix, frac_coord2,
                                 [pymatgen.Element(str(spc)).number for spc in structure.species]))
        #
        # Lattice information
        #
        avec = skp["primitive_lattice"]
        bvec = skp["reciprocal_primitive_lattice"]
        pos = skp["primitive_positions"]
        nat = len(skp["primitive_types"])
        atom = [str(get_el_sp(iat)) for iat in skp["primitive_types"]]
        typ = set(atom)
        ntyp = len(typ)
        #
        # WFC and Rho cutoff
        #
        ecutwfc = 0.0
        ecutrho = 0.0
        for ityp in typ:
            if ecutwfc < ecutwfc_dict[str(ityp)]:
                ecutwfc = ecutwfc_dict[str(ityp)]
            if ecutrho < ecutrho_dict[str(ityp)]:
                ecutrho = ecutrho_dict[str(ityp)]
        #
        # k grid
        #
        nk = numpy.zeros(3, numpy.int_)
        for ii in range(3):
            norm = numpy.sqrt(numpy.dot(bvec[ii][:], bvec[ii][:]))
            nk[ii] = round(norm / 0.16)
            if nk[ii] == 0:
                nk[ii] = 1
        #
        # SCF file
        #
        with open("scf.in", 'w') as f:
            print("&CONTROL", file=f)
            print(" calculation = \'scf\'", file=f)
            print("  pseudo_dir = '/home/kawamura/work/pseudo/'", file=f)
            # print("  pseudo_dir = '/work/i0012/i001200/pseudo/'", file=f)
            print("/", file=f)
            print("&SYSTEM", file=f)
            print("       ibrav = 0", file=f)
            print("         nat = %d" % nat, file=f)
            print("        ntyp = %d" % ntyp, file=f)
            print("     ecutwfc = %f" % ecutwfc, file=f)
            print("     ecutrho = %f" % ecutrho, file=f)
            print(" occupations = \'tetrahedra_opt\'", file=f)
            print("/", file=f)
            print("&ELECTRONS", file=f)
            print(" mixing_beta = 0.3", file=f)
            print("/", file=f)
            print("CELL_PARAMETERS angstrom", file=f)
            for ii in range(3):
                print(" %f %f %f" % (avec[ii, 0], avec[ii, 1], avec[ii, 2]), file=f)
            print("ATOMIC_SPECIES", file=f)
            for ityp in typ:
                print(" %s %f %s" % (ityp, pymatgen.Element(ityp).atomic_mass, pseudo_dict[str(ityp)]), file=f)
            print("ATOMIC_POSITIONS crystal", file=f)
            for iat in range(nat):
                print(" %s %f %f %f" % (
                    atom[iat], pos[iat][0], pos[iat][1], pos[iat][2]), file=f)
            print("K_POINTS automatic", file=f)
            print(" %d %d %d 0 0 0" % (nk[0], nk[1], nk[2]), file=f)
        #
        # Run DFT
        #
        subprocess.call("mpirun -hostfile $PBS_NODEFILE ~/bin/pw.x -nk 28 -in scf.in > scf.out", shell=True)
        # subprocess.call("mpirun -np 2 ~/bin/pw.x -nk 2 -in scf.in > scf.out", shell=True)
        #
        # Extract DOS
        #
        xmlfile = os.path.join("pwscf.save/", 'data-file-schema.xml')
        tree = ElementTree.parse(xmlfile)
        root = tree.getroot()
        child = root.find('output').find('band_structure')
        efermi = float(child.find('fermi_energy').text) * 13.60569228 * 2.0
        #
        # DOS file
        #
        with open("dos.in", 'w') as f:
            print("&DOS", file=f)
            print("      emin = %f" % efermi, file=f)
            print("      emax = %f" % efermi, file=f)
            print("    deltae = 0.1", file=f)
            print("/", file=f)
        #
        # Run DOS
        #
        subprocess.call("mpirun -hostfile $PBS_NODEFILE ~/bin/dos.x -in dos.in > dos.out", shell=True)
        # subprocess.call("mpirun -np 2 ~/bin/dos.x -in dos.in > dos.out", shell=True)
        #
        with open("pwscf.dos", "r") as f:
            f.readline()
            line = f.readline()
            dos = float(line.split()[1]) / nat
        #
        print(self.filename[action[0]], efermi, dos)
        #
        return dos


descriptor, filename = load_data()
descriptor = combo.misc.centering(descriptor)
policy = combo.search.discrete.policy(test_X=descriptor)
policy.set_seed(1)
random_search = policy.random_search(max_num_probes=5, simulator=Simulator())
bayes_search = policy.bayes_search(max_num_probes=30, simulator=Simulator(), score='TS',
                                   interval=1, num_rand_basis=5000)

print('f(x)=')
print(bayes_search.fx[0:bayes_search.total_num_search])
best_fx, best_action = bayes_search.export_all_sequence_best_fx()
print('current best')
print(best_fx)
print('current best action=')
print(best_action)
print('history of chosen actions=')
print(bayes_search.chosed_actions[0:bayes_search.total_num_search])
