import { Injectable } from '@angular/core';
import { BehaviorSubject } from 'rxjs';

@Injectable({
  providedIn: 'root'
})
export class AuthService {
  private isConnectedSubject = new BehaviorSubject<boolean>(false);
  isConnected$ = this.isConnectedSubject.asObservable();

  private userRole: 'admin' | 'user' | null = null;
  public userName: string | null = null;

  constructor() {
    const token = localStorage.getItem('token');
    if (token) {
      this.isConnectedSubject.next(true);
      // Simuler la récupération du nom et du rôle
      // this.userName = "Utilisateur"; 
    }
  }

  get isConnected(): boolean {
    return this.isConnectedSubject.value;
  }

  get isAdmin(): boolean {
    return this.userRole === 'admin';
  }

  login(credentials: any) {
    // Simuler un appel API
    // this.isConnectedSubject.next(true);
    // this.userRole = 'admin'; // Pour le test
    // this.userName = 'Jean Dupont';
    // localStorage.setItem('token', 'votre_jwt_ici');
  }

  logout() {
    this.isConnectedSubject.next(false);
    this.userRole = null;
    this.userName = null;
    localStorage.removeItem('token');
  }
}