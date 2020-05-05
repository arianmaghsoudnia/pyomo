import pyutilib.subprocess.GlobalData
pyutilib.subprocess.GlobalData.DEFINE_SIGNAL_HANDLERS_DEFAULT = False

import pyomo.environ as pyo
import numpy as np
import matplotlib.pyplot as plt
from pyomo.opt import SolverFactory
import os
import sys

##Declare model (to be used)
#concrete or abstract models are two different pyomo models
m = pyo.ConcreteModel()

##SET
#SET I = all Units
m.I = pyo.Set(initialize = ['ICE','Boiler1','Boiler2','HP'])
#now let's define the subsets.
#We can have electricity consuming devices or fuel consuming devices as the inlet and electricity or heat as the output.
#Our subsets are defined within the main set I, which we indicate by the command within.
m.I_f = pyo.Set(within = m.I, initialize = ['ICE','Boiler1','Boiler2'])
m.I_el = pyo.Set(within = m.I, initialize = ['ICE'])
m.I_th = pyo.Set(within = m.I, initialize = ['ICE','Boiler1','Boiler2','HP'])
#this is heat pump which consumes electricity
m.I_el_consum = pyo.Set(within = m.I, initialize = ['HP'])
#We don't have organic rankine cycle; if we had, we could define a set for later setting the constraint of maximum startups.
#m.I_ORC = pyo.Set(within = m.I, initialize = ['ORC'])

#SET T = all time instants (24 hs in a day)
T = 24 #elemnts in the Set
m.T= pyo.RangeSet(0,T-1)

#Set S = all storages
#we have two types of storages, electrical(BATTERT), or thermal storage
m.S = pyo.Set(initialize = ['TES','BAT'])
m.S_el = pyo.Set(within = m.S, initialize = ['BAT'])
m.S_th = pyo.Set(within = m.S, initialize = ['TES'])

##Variables
#Real Variables
#for the machines that have fuel as the input, second term is time, and the third one is the type of variable.
m.f = pyo.Var(m.I_f,m.T,domain = pyo.NonNegativeReals)
m.q = pyo.Var(m.I_th,m.T,domain = pyo.NonNegativeReals)
m.p = pyo.Var(m.I_el,m.T,domain = pyo.NonNegativeReals)
m.el_in = pyo.Var(m.I_el_consum,m.T,domain = pyo.NonNegativeReals)

#Binary
#This is the on/off variable
m.z = pyo.Var(m.I,m.T,domain = pyo.Binary)
#Now we define the startup variable.
m.dSU = pyo.Var(m.I,m.T,domain = pyo.Binary)
#We have not defined the shut-down variable because in this case we had zero cost for shutdown so we have no constraint

#Related to storage
# u is the state of charge of storage S at time T 
m.u = pyo.Var(m.S,m.T,domain = pyo.NonNegativeReals)
#We have Charge and Discharge variables which will be used in energy balance constraint 
m.Charge = pyo.Var(m.S,m.T,domain = pyo.NonNegativeReals)
m.Discharge = pyo.Var(m.S,m.T,domain = pyo.NonNegativeReals)

#Electricity - Grid
#We can buy or sell electricity to the grid. The variable is only dependant on time 
m.El_buy = pyo.Var(m.T,domain = pyo.NonNegativeReals)
m.El_sell = pyo.Var(m.T,domain = pyo.NonNegativeReals)


##Parameters [Data]
#This is the part special to each group; we have to insert the electricity and the thermal demand.
#The Data below is inserted from Precept2_MESlab_data.xlsx - Demands and Prices Sheet
d_el = [1082.5,1073.1,1070.7,1079.7,1079.5,1100.1,1178.0,1329.2,1670.6,1971.4,2107.7,2133.9,2104.2,2036.0,2057.0,2089.3,2000.1,1915.5,1763.4,1575.1,1370.9,1208.1,1155.4,1102.6]
d_th = [300.9,298.4,303.0,552.6,842.8,3866.3,2436.7,2667.1,2114.5,1502.1,998.6,772.4,738.3,313.7,0.0,0.0,0.0,354.2,332.9,552.6,296.0,322.2,469.4,295.9]

El_price_sell = [0.0561,0.0494,0.0457,0.0438,0.0431,0.0465,0.0550,0.0621,0.0750,0.0675,0.0602,0.0582,0.0562,0.0556,0.0561,0.0598,0.0630,0.0632,0.0667,0.0737,0.0746,0.0725,0.0632,0.0550]
El_price_buy = [0.1272,0.1272,0.1272,0.1272,0.1272,0.1272,0.1272,0.1496,0.1514,0.1514,0.1514,0.1514,0.1514,0.1514,0.1514,0.1514,0.1514,0.1514,0.1514,0.1496,0.1496,0.1496,0.1496,0.1272]
# From the text with the unit $/Kwh
NG_price = 0.03
Biomass_price = 0.025

#for all the units that consume fuel we assign a Python dictionary.
#This way of modifying is espcially usefull if we want to modify later the prices
Fuel_cost = {'ICE':NG_price,'Boiler1':NG_price,'Boiler2':NG_price}
#Linear Performance maps 
#The performance maps provides the output- for example heat ouput-  by relating the input-for example the fuel consumption- by coefficient "a"  with a constant term with factor(b)
#WE need to define a and b which are the data
#The "a" parameters will be used in different constraints for thermal or electrical consumption 

#Units that have a thermal power output under subset of I_th
a_th = {'ICE':0.439,'Boiler1':0.976,'Boiler2':0.945,'HP':3.590}
b_th = {'ICE':-74.75,'Boiler1':-84.75,'Boiler2':-54.33,'HP':-51.28}

#Only the ICE produces electricity
a_el = {'ICE':0.49}
b_el = {'ICE':-191.03}

#Minimum inputs for each unit
MinIn = {'ICE':1829.3,'Boiler1':662.1,'Boiler2':424.42,'HP':83.3}
MaxIn = {'ICE':3658.5,'Boiler1':2648.3,'Boiler2':1697.70,'HP':641.0}
#Ramp-up limit equals to maximum limit because no unit has a ramp up limit
RUlim = {'ICE':3658.5,'Boiler1':2648.3,'Boiler2':1697.70,'HP':641.0}
#There are not maximum startups limit so we use the maximum time available(24 hours) as the limit
#In the case of ORC we can only have one startup so this number would be equal to one. 
Max_n_SU = {'ICE':T,'Boiler1':T,'Boiler2':T,'HP':T}
#The follwing is the case specific operating and startup cost from the excel for the group C.
OM_cost = {'ICE':9.46,'Boiler1':0,'Boiler2':0,'HP':13.28}
SU_cost = {'ICE':8.45,'Boiler1':4,'Boiler2':2.56,'HP':9.13}

#Maximum storage capacity; The Unit is Kwh; If the storage is unavailable we set it to zero
MaxC = {'TES':0,'BAT':0}
#Only for electricity we have charge and dischare efficiency; for the heat storage, we have thermal loss and therefore dissipation efficiency. 
eta_ch ={'BAT':0.97}
eta_disch = {'BAT':0.97}
eta_diss = {'TES':0.995}

##Obejctive Function

#We have to add the fuel cost, the O&M Cost and the Sold-Bought Electricity the function obj_func does this
def obj_func(m):
    machine_fuel_cost = sum(Fuel_cost[i]*m.f[i,t] for i in m.I_f for t in m.T)
    machine_OM_cost = sum(OM_cost[i]*m.z[i,t] for i in m.I for t in m.T)
    machine_SU_cost = sum(SU_cost[i]*m.dSU[i,t] for i in m.I for t in m.T)
    grid_SellBuy = sum(El_price_buy[t]*m.El_buy[t] - El_price_sell[t]*m.El_sell[t] for t in m.T)
    return machine_fuel_cost + machine_OM_cost + machine_SU_cost + grid_SellBuy
#This is the syntax to minimize the objective function. 
m.obj = pyo.Objective(rule = obj_func, sense = pyo.minimize)


##Constrains
#El balance
#This function returns if the electric balance is satisfied.
#We basically set a rule as a function and then assign it to a constraint by the pyomo's module.
def el_balance_rule(m,t):
    return sum(m.p[i,t] for i in m.I_el) - sum(m.el_in[i,t] for i in m.I_el_consum) + m.El_buy[t] - m.El_sell[t] + sum(m.Discharge[s,t] for s in m.S_el) - sum(m.Charge[s,t] for s in m.S_el) == d_el[t]
m.el_balance_con = pyo.Constraint(m.T, rule = el_balance_rule)

#Th balance
#for the Heat Balance, we do the same as the electricity balance 
def th_balance_rule(m,t):
    return sum(m.q[i,t] for i in m.I_th) + sum(m.Discharge[s,t] for s in m.S_th) - sum(m.Charge[s,t] for s in m.S_th) == d_th[t]
m.th_balance_con = pyo.Constraint(m.T, rule = th_balance_rule)

#Now we will define the performance maps of the system
#a and b parameters should now be appeared in the constraints.

#El production
#We only have units that produce electricity and uses fuel as the input 
#The fixed term is related to the on/off variable.
def el_prod_rule(m,i,t):
        return m.p[i,t] == a_el[i]*m.f[i,t] + b_el[i]*m.z[i,t]
m.el_prod_con = pyo.Constraint(m.I_el, m.T, rule = el_prod_rule)

#Th production
#In the case of thermal production we have to distinguish between two systems.
#The first type of system uses fuel as the input wheras the second type of system uses electricity as the input 
#To distinguish the two cases we use an if/else logic.
#We could have used to different rules but this way it is easier.
def th_prod_rule(m,i,t):
    if i in m.I_f:
        return m.q[i,t] == a_th[i]*m.f[i,t] + b_th[i]*m.z[i,t]
    elif i in m.I_el_consum:
        return m.q[i,t] == a_th[i]*m.el_in[i,t] + b_th[i]*m.z[i,t]
m.th_prod_con = pyo.Constraint(m.I_th, m.T, rule = th_prod_rule)

#Operating Range Min
#If the system is on, the input which can be fuel or electricity should be greater or equal to the min input
#Again we have to distinguish between the different systems.
def min_input_rule(m,i,t):
    if i in m.I_f:
        return m.f[i,t] >= MinIn[i]*m.z[i,t]
    elif i in m.I_el_consum:
        return m.el_in[i,t] >= MinIn[i]*m.z[i,t]
m.min_input_con = pyo.Constraint(m.I, m.T,rule = min_input_rule)

#Operating Range Max
#If the system is on, the input which can be fuel or electricity should be less or equal to the max input
#Again we have to distinguish between the different systems.
def max_input_rule(m,i,t):
    if i in m.I_f:
        return m.f[i,t] <= MaxIn[i]*m.z[i,t]
    elif i in m.I_el_consum:
        return m.el_in[i,t] <= MaxIn[i]*m.z[i,t]
m.max_input_con = pyo.Constraint(m.I, m.T, rule = max_input_rule)

#Logical SU
#Here we have to relate the on/off variable with the startup variables 
#For times greater than 0 the startup should be consistant with the dSU constraint. 
#When t=0, t-1 is not defined. if we have t=0; we can say that what happens at that day could be assumed equal to the last hour of the previous day
def logical_SU_rule(m,i,t):
    if t > 0:
        return m.z[i,t] - m.z[i,t-1] <= m.dSU[i,t]
    elif t == 0:
        return m.z[i,0] - m.z[i,T-1] <= m.dSU[i,0]
m.logical_SU_con = pyo.Constraint(m.I, m.T, rule = logical_SU_rule)

#Ramp-Up limit
#As for ramp up we have two different sources as the input that we have to distinguish using if statement.
#For times greater than 0 the ramp-up should be consistant with the dSU constraint. 
#When t=0, t-1 is not defined. if we have t=0; we can say that what happens at that day could be assumed the same as the last hour of the previous day
def ramp_up_rule(m,i,t):
    if i in m.I_f:
        if t > 0:
            return m.f[i,t] - m.f[i,t-1] <= RUlim[i]*m.z[i,t]
        elif t == 0:
            return m.f[i,0] - m.f[i,T-1] <= RUlim[i]*m.z[i,0]
    elif i in m.I_el_consum:
        if t > 0:
            return m.el_in[i,t] - m.el_in[i,t-1] <= RUlim[i]*m.z[i,t]
        elif t == 0:
            return m.el_in[i,0] - m.el_in[i,T-1] <= RUlim[i]*m.z[i,0]  
m.ramp_up_con = pyo.Constraint(m.I,m.T,rule = ramp_up_rule)

#In our case we have no ORC; the following function could be used in such case.
"""def max_su_rule(m,i,t):
 return sum(m.dSU[i,t] for i in m.I_ORC for t in m.T)<=1)
m.max_su_con = pyo.Constraint(m.T, rule = max_su_rule)   
"""
#Th Storage Balance
#This function is applied to fullfill the thermal storage balance equation.
#It should be noted that for time 0 the constraint is being applied with the logic of the previous section.
def th_storage_rule(m,s,t):
    if t > 0:
        return m.u[s,t] - m.u[s,t-1]*eta_diss[s] == m.Charge[s,t] - m.Discharge[s,t]    
    elif t == 0:
        return m.u[s,0] - m.u[s,T-1]*eta_diss[s] == m.Charge[s,0] - m.Discharge[s,0]  
m.th_storage_con = pyo.Constraint(m.S_th,m.T, rule = th_storage_rule)

#El Storage Balance
def el_storage_rule(m,s,t):
    if t > 0:
        return m.u[s,t] - m.u[s,t-1] == m.Charge[s,t]*eta_ch[s] - m.Discharge[s,t]/eta_disch[s]    
    elif t == 0:
        return m.u[s,0] - m.u[s,T-1] == m.Charge[s,0]*eta_ch[s] - m.Discharge[s,0]/eta_disch[s]
m.el_storage_con = pyo.Constraint(m.S_el,m.T, rule = el_storage_rule)
    
def Capacity_Rule(m,s,t):
    return m.u[s,t] <= MaxC[s]
m.Capacity_con = pyo.Constraint(m.S,m.T, rule = Capacity_Rule)

solvername='cbc'
solverpath_folder='~/anaconda3/pkgs/coincbc-2.10.5-hab63836_0'
solverpath_exe='~/anaconda3/pkgs/coincbc-2.10.5-hab63836_0/bin'
sys.path.append(solverpath_folder)

pyo.SolverFactory(solvername,mipgap = 0.005).solve(m).write()

electricity = {}
electricity_cons = {}
electricity_ch = {}
electricity_dis = {}
heat = {}
heat_ch = {}
heat_dis = {}
level_th = {}
level_el = {}

for i in m.I.value: 
   if i in m.I_el:
      electricity[i] = np.array(list(m.p[i,:].value))
   if i in m.I_th:
      heat[i] = np.array(list(m.q[i,:].value))
   if i in m.I_el_consum:
      electricity_cons[i] = np.array(list(m.el_in[i,:].value))
for s in m.S.value:
   if s in m.S_el:
      electricity_ch[s] = np.array(list(m.Charge[s,:].value)) 
      electricity_dis[s] = np.array(list(m.Discharge[s,:].value)) 
      level_el[s] = np.array(list(m.u[s,:].value))
   if s in m.S_th:
      heat_ch[s] = np.array(list(m.Charge[s,:].value))
      heat_dis[s] = np.array(list(m.Discharge[s,:].value))
      level_th[s]  = np.array(list(m.u[s,:].value))
electricity_buy = np.array(list(m.El_buy[:].value))
electricity_sell = np.array(list(m.El_sell[:].value))

times = range(T)
barplot = plt.figure()
# adding electricity produced by machines 
cm_el = 0
for i in m.I_el:
    plt.bar(times, height = electricity[i], bottom = cm_el, label = i) 
    cm_el += np.array(electricity[i])
# minus electricity consumed
cm_el_neg = 0
for i in m.I_el_consum:
    plt.bar(times, height = -electricity_cons[i], bottom = -cm_el_neg, label = i) 
    cm_el_neg += np.array(electricity_cons[i])
#grid
plt.bar(times, height = electricity_buy, bottom = cm_el, label = 'Grid buy') 
cm_el += electricity_buy
plt.bar(times, height = -electricity_sell, bottom = -cm_el_neg, label = 'Grid sell') 
cm_el_neg += electricity_sell
#adding battery discharge/charge
for s in m.S_el:
    plt.bar(times, height = electricity_dis[s], bottom = cm_el, label = s+' discharge')
    cm_el += np.array(electricity_dis[s])
    plt.bar(times, height = -electricity_ch[s], bottom = -cm_el_neg, label = s+' charge')
    cm_el_neg += np.array(electricity_ch[s])

#el Demand
plt.plot(times, d_el, '--k', label = 'El Demand')

#Battery Level
for s in m.S_el:
    plt.plot(times, level_el[s], '--r',  label = 'level '+s)
plt.legend(loc='upper center', bbox_to_anchor=(0.5, -0.08))
plt.title('Electricity Profiles')
plt.ylabel('KWh')

#Heat
barplot = plt.figure()

#adding heat produced by machines
cm_th = 0
for i in m.I_th:
    plt.bar(times, height = heat[i], bottom = cm_th, label = i)
    cm_th += np.array(heat[i])

#adding storage discharged/charged
cm_th_neg = 0
for s in m.S_th:
    plt.bar(times, height =heat_dis[s], bottom =cm_th, label = s+' discharge')
    cm_th += np.array(heat_dis[s])
    plt.bar(times, height = -heat_ch[s], bottom = -cm_th_neg, label = s+' charge')
    cm_th_neg += np.array(heat_ch[s])
    
#th Demand
plt.plot(times, d_th, '--k', label = 'Heat Demand')

#TES Level
for s in m.S_th:
    plt.plot(times, level_th[s], '--r', label = 'level '+s) 
plt.legend(loc='upper center', bbox_to_anchor=(0.5,-0.08))
plt.title('Heat Profiles')
plt.ylabel('KWh')


