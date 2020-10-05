import pickle
import yaml
from os.path import join
from random import sample
from pyomo.opt import SolverFactory
from numpy import zeros, argmax
import argparse
import time

from src.helpers import read_inputs, init_folder, custom_log, remove_garbage, generate_jl_output
from src.models import preprocess_input_data, build_model, build_model_lp
from src.tools import retrieve_location_dict, retrieve_site_data, retrieve_location_dict_jl, retrieve_index_dict

def parse_args():

    parser = argparse.ArgumentParser(description='Command line arguments.')

    parser.add_argument('-c', '--global_thresh', type=int, help='Global threshold')
    parser.add_argument('-tl', '--time_limit', type=int, help='Solver time limit')
    parser.add_argument('-th', '--threads', type=int, help='Number of threads')

    parsed_args = vars(parser.parse_args())

    return parsed_args

parameters = read_inputs('../config_model.yml')
keepfiles = parameters['keep_files']

#input_dict = preprocess_input_data(parameters)
#pickle.dump(input_dict['criticality_data'], open('criticality_data_test.p', 'wb'))

#cf_data = input_dict['capacity_factor_data']['EU']['wind_onshore'].unstack('locations')
#cf_data.to_netcdf('cf_data.nc')

#import sys
#sys.exit()

criticality_data = pickle.load(open('criticality_matrix.p', 'rb'))
coordinates_data = pickle.load(open('coordinates_data.p', 'rb'))

if parameters['solution_method']['BB']['set']:

    args = parse_args()

    parameters['solution_method']['BB']['timelimit'] = args['time_limit']
    parameters['solution_method']['BB']['threads'] = args['threads']
    parameters['solution_method']['BB']['c'] = args['global_thresh']

    custom_log(' BB chosen to solve the IP.')

    solver = parameters['solution_method']['BB']['solver']
    MIPGap = parameters['solution_method']['BB']['mipgap']
    TimeLimit = parameters['solution_method']['BB']['timelimit']
    Threads = parameters['solution_method']['BB']['threads']
    c = parameters['solution_method']['BB']['c']

    if not isinstance(parameters['solution_method']['BB']['c'], int):
        raise ValueError(' Values of c have to be integers for the Branch & Bound set-up.')    

    total_locs = criticality_data.shape[1]
    output_folder = init_folder(parameters, total_locs, suffix='_c' + str(parameters['solution_method']['BB']['c']) + '_LP')
    with open(join(output_folder, 'config_model.yaml'), 'w') as outfile:
        yaml.dump(parameters, outfile, default_flow_style=False, sort_keys=False)

    # Solver options for the MIP problem
    opt = SolverFactory(solver)
    opt.options['MIPGap'] = MIPGap
    opt.options['Threads'] = Threads
    opt.options['TimeLimit'] = TimeLimit

    #instance, indices = build_model(parameters, input_dict, output_folder, write_lp=False)
    instance = build_model_lp(parameters, criticality_data, coordinates_data, output_folder, write_lp=False)
    custom_log(' Sending model to solver.')

    results = opt.solve(instance, tee=False, keepfiles=False, report_timing=False,
                        logfile=join(output_folder, 'solver_log.log'))

    l = []
    for item in instance.x:
       l.append(instance.x[item].value)
    from collections import Counter
    print(Counter(l))

    #objective = instance.objective()
    #comp_location_dict = retrieve_location_dict(instance, parameters, input_dict, indices)
    #retrieve_site_data(c, parameters, input_dict, output_folder, comp_location_dict, objective)


elif parameters['solution_method']['RAND']['set']:

    custom_log(' Locations to be chosen via random search.')

    if not isinstance(parameters['solution_method']['RAND']['c'], list):
        raise ValueError(' Values of c have to provided as list for the RAND set-up.')
    if len(parameters['technologies']) > 1:
        raise ValueError(' This method is currently implemented for one single technology only.')

    import julia
    jl_dict = generate_jl_output(parameters['deployment_vector'],
                                 criticality_data,
                                 coordinates_data)
    jl = julia.Julia(compiled_modules=False)
    from julia.api import Julia
    fn = jl.include("jl/main_heuristics.jl")

    for c in parameters['solution_method']['RAND']['c']:
        print('Running heuristic for c value of', c)
        start = time.time()
        jl_selected, jl_objective, jl_traj = fn(jl_dict['index_dict'],
                                             jl_dict['deployment_dict'],
                                             jl_dict['criticality_matrix'],
                                             c,
                                             parameters['solution_method']['HEU']['neighborhood'],
                                             parameters['solution_method']['RAND']['no_iterations'],
                                             parameters['solution_method']['RAND']['no_epochs'],
                                             parameters['solution_method']['HEU']['initial_temp'],
                                             parameters['solution_method']['RAND']['no_runs'],
                                             parameters['solution_method']['RAND']['algorithm'])
        end = time.time()
        noruns = parameters['solution_method']['RAND']['no_runs']
        dt = (end-start)/noruns
        print(f'Average time per run: {dt}')

        nolocs = criticality_data.shape[1]
        #print(nolocs)
        output_folder = init_folder(parameters, nolocs, suffix='_c' + str(c) + '_RS')
        
        #with open(join(output_folder, 'config_model.yaml'), 'w') as outfile:
        #    yaml.dump(parameters, outfile, default_flow_style=False, sort_keys=False)
        pickle.dump(jl_selected, open(join(output_folder, 'solution_matrix.p'), 'wb'))
        pickle.dump(jl_objective, open(join(output_folder, 'objective_vector.p'), 'wb'))
        pickle.dump(jl_traj, open(join(output_folder, 'trajectory_matrix.p'), 'wb'))
        #if c == parameters['solution_method']['HEU']['c'][0]:
        #    pickle.dump(criticality_data, open(join(output_folder, 'criticality_matrix.p'), 'wb'),
        #                protocol=4)


    #c = parameters['solution_method']['RAND']['c']
    #n, dict_deployment, partitions, indices = retrieve_index_dict(parameters, input_dict['coordinates_data'])

    #for c in parameters['solution_method']['RAND']['c']:

    #    print('Running random search for c value of', c)

    #    seed = parameters['solution_method']['RAND']['seed']
    #    for run in range(parameters['solution_method']['RAND']['no_runs']):

    #        output_folder = init_folder(parameters, input_dict, suffix='_c'+ str(c) + '_rand_seed' + str(seed))
    #        seed += 1

    #        with open(join(output_folder, 'config_model.yaml'), 'w') as outfile:
    #            yaml.dump(parameters, outfile, default_flow_style=False, sort_keys=False)

    #        it = parameters['solution_method']['RAND']['no_iterations']*parameters['solution_method']['RAND']['no_epochs']
    #        best_objective = 0.
    #        best_random_locations = []

    #        for i in range(it):

    #            random_locations = []
    #            for region in parameters['deployment_vector'].keys():
    #                for tech in parameters['technologies']:
    #                    population = input_dict['coordinates_data'][region][tech]
    #                    k = parameters['deployment_vector'][region][tech]
    #                    random_locations.extend(sample(population, k))

    #            all_locations = []
    #            for region in parameters['deployment_vector'].keys():
    #                for tech in parameters['technologies']:
    #                    all_locations.extend(input_dict['coordinates_data'][region][tech])
    #            random_locations_index = []
    #            for loc in random_locations:
    #                idx = all_locations.index(loc)
    #                random_locations_index.append(idx + 1)

    #            random_locations_index = [i-1 for i in sorted(random_locations_index)]

    #            xs = zeros(shape=input_dict['criticality_data'].shape[1])
    #            xs[random_locations_index] = 1

    #            D = input_dict['criticality_data']
    #            objective = (D.dot(xs) >= c).astype(int).sum()

    #            if objective > best_objective:
    #                best_objective = objective
    #                best_random_locations = random_locations

    #        random_locations_dict = {parameters['technologies'][0]: best_random_locations}
    #        retrieve_site_data(c, parameters, input_dict, output_folder, random_locations_dict, best_objective)


elif parameters['solution_method']['HEU']['set']:

    custom_log(' HEU chosen to solve the IP. Opening a Julia instance.')
    import julia

    if not isinstance(parameters['solution_method']['HEU']['c'], list):
        raise ValueError(' Values of c have to elements of a list for the heuristic set-up.')

    #_, _, _, indices = retrieve_index_dict(parameters, input_dict['coordinates_data'])

    jl_dict = generate_jl_output(parameters['deployment_vector'],
                                 criticality_data,
                                 coordinates_data)
    print(jl_dict['index_dict'])
    jl = julia.Julia(compiled_modules=False)
    from julia.api import Julia
    fn = jl.include("jl/main_heuristics.jl")

    for c in parameters['solution_method']['HEU']['c']:
        print('Running heuristic for c value of', c)
        start = time.time()
        jl_selected, jl_objective, jl_traj = fn(jl_dict['index_dict'],
                                             jl_dict['deployment_dict'],
                                             jl_dict['criticality_matrix'],
                                             c,
                                             parameters['solution_method']['HEU']['neighborhood'],
                                             parameters['solution_method']['HEU']['no_iterations'],
                                             parameters['solution_method']['HEU']['no_epochs'],
                                             parameters['solution_method']['HEU']['initial_temp'],
                                             parameters['solution_method']['HEU']['no_runs'],
                                             parameters['solution_method']['HEU']['algorithm'])
        end = time.time()
        noruns = parameters['solution_method']['HEU']['no_runs']
        dt = (end-start)/noruns
        print(f'Average time per run: {dt}')
        
        nolocs = criticality_data.shape[1]

        output_folder = init_folder(parameters, nolocs, suffix='_c' + str(c) + '_MIRSA_check')
        
        #with open(join(output_folder, 'config_model.yaml'), 'w') as outfile:
        #    yaml.dump(parameters, outfile, default_flow_style=False, sort_keys=False)
        pickle.dump(jl_selected, open(join(output_folder, 'solution_matrix.p'), 'wb'))
        pickle.dump(jl_objective, open(join(output_folder, 'objective_vector.p'), 'wb'))
        pickle.dump(jl_traj, open(join(output_folder, 'trajectory_matrix.p'), 'wb'))
        #if c == parameters['solution_method']['HEU']['c'][0]:
        #    pickle.dump(criticality_data, open(join(output_folder, 'criticality_matrix.p'), 'wb'),
        #                protocol=4)

        #if parameters['solution_method']['HEU']['which_sol'] == 'max':
        #    jl_objective_seed = max(jl_objective)
        #    jl_selected_seed = jl_selected[argmax(jl_objective), :]

        #    output_folder = init_folder(parameters, input_dict, suffix='_c' + str(c))
        #    with open(join(output_folder, 'config_model.yaml'), 'w') as outfile:
        #        yaml.dump(parameters, outfile, default_flow_style=False, sort_keys=False)

        #    jl_locations = retrieve_location_dict_jl(jl_selected_seed, parameters, input_dict, indices)
        #    retrieve_site_data(parameters, input_dict, output_folder, jl_locations, jl_objective_seed)

        #else: #'rand'
        #    seed = parameters['solution_method']['HEU']['seed']
        #    for i in range(jl_selected.shape[0]):

        #        output_folder = init_folder(parameters, input_dict, suffix='_c' + str(c) + '_seed' + str(seed) + '_MIRSA')
        #        seed += 1

        #        with open(join(output_folder, 'config_model.yaml'), 'w') as outfile:
        #            yaml.dump(parameters, outfile, default_flow_style=False, sort_keys=False)

        #        jl_selected_seed = jl_selected[i, :]
        #        jl_objective_seed = jl_objective[i]

        #        jl_locations = retrieve_location_dict_jl(jl_selected_seed, parameters, input_dict, indices)
        #        retrieve_site_data(c, parameters, input_dict, output_folder, jl_locations, jl_objective_seed)

elif parameters['solution_method']['RGH']['set']:

    custom_log(' RGH chosen to solve the IP. Opening a Julia instance.')
    import julia

    if not isinstance(parameters['solution_method']['HEU']['c'], list):
        raise ValueError(' Values of c have to elements of a list for the heuristic set-up.')

    jl_dict = generate_jl_output(parameters['deployment_vector'],
                                 input_dict['criticality_data'],
                                 input_dict['coordinates_data'])

    jl = julia.Julia(compiled_modules=False)
    from julia.api import Julia

    fn = jl.include("jl/main_heuristics.jl")

    for c in parameters['solution_method']['RGH']['c']:
        print('Running heuristic for c value of', c)
        start = time.time()
        jl_selected, jl_objective, jl_traj = fn(jl_dict['index_dict'],
                                                jl_dict['deployment_dict'],
                                                jl_dict['criticality_matrix'],
                                                c,
                                                parameters['solution_method']['HEU']['neighborhood'],
                                                parameters['solution_method']['HEU']['no_iterations'],
                                                parameters['solution_method']['HEU']['no_epochs'],
                                                parameters['solution_method']['HEU']['initial_temp'],
                                                parameters['solution_method']['RGH']['no_runs'],
                                                parameters['solution_method']['RGH']['algorithm'])
        end = time.time()
        noruns = parameters['solution_method']['HEU']['no_runs']
        dt = (end - start) / noruns
        print(f'Average time per run: {dt}')

        output_folder = init_folder(parameters, input_dict, suffix='_c' + str(c) + '_RGH')

        with open(join(output_folder, 'config_model.yaml'), 'w') as outfile:
            yaml.dump(parameters, outfile, default_flow_style=False, sort_keys=False)
        pickle.dump(jl_selected, open(join(output_folder, 'solution_matrix.p'), 'wb'))
        pickle.dump(jl_objective, open(join(output_folder, 'objective_vector.p'), 'wb'))
        pickle.dump(jl_traj, open(join(output_folder, 'trajectory_matrix.p'), 'wb'))
        if c == parameters['solution_method']['HEU']['c'][0]:
            pickle.dump(input_dict['criticality_data'], open(join(output_folder, 'criticality_matrix.p'), 'wb'),
                        protocol=4)

elif parameters['solution_method']['GAS']['set']:

    custom_log(' GAS chosen to solve the IP. Opening a Julia instance.')
    import julia

    jl_dict = generate_jl_output(parameters['deployment_vector'],
                                 criticality_data,
                                 coordinates_data)

    jl = julia.Julia(compiled_modules=False)
    from julia.api import Julia

    fn = jl.include("jl/main_heuristics.jl")

    for c in parameters['solution_method']['GAS']['c']:
        print('Running heuristic for c value of', c)
        start = time.time()
        jl_selected, jl_objective, jl_traj = fn(jl_dict['index_dict'],
                                                jl_dict['deployment_dict'],
                                                jl_dict['criticality_matrix'],
                                                c,
                                                parameters['solution_method']['HEU']['neighborhood'],
                                                parameters['solution_method']['HEU']['no_iterations'],
                                                parameters['solution_method']['HEU']['no_epochs'],
                                                parameters['solution_method']['HEU']['initial_temp'],
                                                parameters['solution_method']['GAS']['no_runs'],
                                                parameters['solution_method']['GAS']['algorithm'])
        end = time.time()
        noruns = parameters['solution_method']['GAS']['no_runs']
        dt = (end-start)/noruns
        print('Average time per run:', dt)

        #import sys
        #sys.exit()

        output_folder = init_folder(parameters, input_dict, suffix='_c' + str(c) + '_' + parameters['solution_method']['GAS']['algorithm'])

        with open(join(output_folder, 'config_model.yaml'), 'w') as outfile:
            yaml.dump(parameters, outfile, default_flow_style=False, sort_keys=False)
        pickle.dump(jl_selected, open(join(output_folder, 'solution_matrix.p'), 'wb'))
        pickle.dump(jl_objective, open(join(output_folder, 'objective_vector.p'), 'wb'))
        pickle.dump(jl_traj, open(join(output_folder, 'trajectory_matrix.p'), 'wb'))
        if c == parameters['solution_method']['HEU']['c'][0]:
            pickle.dump(input_dict['criticality_data'], open(join(output_folder, 'criticality_matrix.p'), 'wb'), protocol=4)

        
else:
    raise ValueError(' This solution method is not available. Retry.')

remove_garbage(keepfiles, output_folder)

